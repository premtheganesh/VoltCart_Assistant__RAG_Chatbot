"""FastAPI entry point. Run with: make api (Swagger UI at http://localhost:8000/docs)"""

import logging
import re
import time
import uuid
from contextlib import ExitStack, asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, chat, health
from app.config import get_settings
from app.logging_setup import configure_logging, request_id
from app.observability import flush_traces

settings = get_settings()
configure_logging(settings.log_level, settings.log_format)
log = logging.getLogger(__name__)
access_log = logging.getLogger("app.request")
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the agent once at startup (models, Postgres memory) and close it at shutdown."""
    from app.graph.agent import open_agent

    with ExitStack() as stack:
        try:
            app.state.agent = stack.enter_context(open_agent(settings))
        except Exception:  # health checks and the admin panel still work; /chat returns 503
            log.exception("agent failed to start")
            app.state.agent = None
        yield
        flush_traces()


app = FastAPI(title="VoltCart Assistant API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    # Only our own sites may call the API from a browser. No cookies are used (the admin token
    # travels in a header), so credentials stay off
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Give every request an id (kept from X-Request-ID if a proxy set one), log one line per
    request with its status and duration, and send the id back so a customer's report of a
    problem can be matched to the logs."""
    incoming = request.headers.get("x-request-id", "")
    rid = incoming if SAFE_ID.match(incoming) else uuid.uuid4().hex[:12]
    token = request_id.set(rid)  # every log line written for this request carries the id
    start = time.perf_counter()
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        # Streamed replies: this is the time to the first byte; chat.py logs the full turn
        access_log.info(
            "%s %s %s", request.method, request.url.path, response.status_code,
            extra={"status": response.status_code, "method": request.method,
                   "path": request.url.path,
                   "duration_ms": round((time.perf_counter() - start) * 1000, 1)},
        )  # fmt: skip
        return response
    except Exception:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        raise
    finally:
        request_id.reset(token)  # only after the last log line of this request


app.include_router(health.router)
app.include_router(chat.router)
app.include_router(admin.router)
