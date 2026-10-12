"""Langfuse tracing: every turn becomes a trace showing each step, prompt, output and timing.

Tracing is optional: without LANGFUSE_* keys in .env the agent runs exactly the same, untraced.
"""

import logging
from functools import lru_cache

from app.config import get_settings

log = logging.getLogger(__name__)


@lru_cache
def _client():
    """The Langfuse client, created once; None when not configured."""
    settings = get_settings()
    if not settings.langfuse_enabled:
        return None
    from langfuse import Langfuse

    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        host=settings.langfuse_host,
        environment=settings.app_env,
    )


def make_tracer(trace_id: str | None = None):
    """A LangChain callback that sends one turn to Langfuse, or None when not configured.

    trace_id (32 lowercase hex chars): use our own id for the trace, so feedback on this answer
    can be attached to it later. A new handler per turn keeps concurrent chats apart."""
    if _client() is None:
        return None
    from langfuse.langchain import CallbackHandler

    return CallbackHandler(
        public_key=get_settings().langfuse_public_key,
        trace_context={"trace_id": trace_id} if trace_id else None,
    )


@lru_cache
def get_langfuse_handler():
    """One shared handler, for scripts that trace without their own trace ids."""
    return make_tracer()


def record_feedback(trace_id: str, rating: int, comment: str | None = None) -> None:
    """Attach a customer's thumbs up/down to the answer's trace (shows up as a score)."""
    client = _client()
    if client is None:
        return
    try:
        client.create_score(
            trace_id=trace_id, name="user_feedback", value=rating, data_type="NUMERIC",
            comment=comment,
        )  # fmt: skip
    except Exception:  # feedback is already saved in Postgres; a tracing outage is not fatal
        log.warning("could not send feedback to Langfuse", exc_info=True)


def flush_traces() -> None:
    """Traces are sent in the background; call before a script exits so none are lost."""
    if (client := _client()) is not None:
        client.flush()
