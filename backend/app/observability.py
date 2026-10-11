"""Langfuse tracing: every turn becomes a trace showing each step, prompt, output and timing.

Tracing is optional: without LANGFUSE_* keys in .env the agent runs exactly the same, untraced.
"""

import logging
from functools import lru_cache

from app.config import get_settings

log = logging.getLogger(__name__)


@lru_cache
def get_langfuse_handler():
    """LangChain callback that sends traces to Langfuse, or None when not configured."""
    settings = get_settings()
    if not settings.langfuse_enabled:
        return None
    from langfuse import Langfuse
    from langfuse.langchain import CallbackHandler

    Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key.get_secret_value(),
        host=settings.langfuse_host,
        environment=settings.app_env,
    )
    return CallbackHandler(public_key=settings.langfuse_public_key)


def flush_traces() -> None:
    """Traces are sent in the background; call before a script exits so none are lost."""
    if get_langfuse_handler() is not None:
        from langfuse import get_client

        get_client().flush()
