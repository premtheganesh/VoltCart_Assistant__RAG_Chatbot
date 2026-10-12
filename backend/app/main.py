"""FastAPI entry point. Run with: make api (Swagger UI at http://localhost:8000/docs)"""

import logging
from contextlib import ExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, chat, health
from app.config import get_settings
from app.observability import flush_traces

settings = get_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
for noisy in ("httpx", "httpcore", "pdfminer"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger(__name__)


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
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(health.router)
app.include_router(chat.router)
app.include_router(admin.router)
