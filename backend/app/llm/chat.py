"""Chat model factory. The provider and model come from .env as "provider:model".

    LLM_MODEL_MAIN=groq:openai/gpt-oss-120b      # writes answers
    LLM_MODEL_SMALL=groq:openai/gpt-oss-20b      # routes and rewrites questions

Switching to another provider (openai:..., anthropic:..., google_genai:...) needs only its
LangChain package installed and its API key set.
"""

from typing import Literal

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from app.config import Settings, get_settings

Role = Literal["main", "small", "safety", "judge"]


def get_chat_model(role: Role, settings: Settings | None = None) -> BaseChatModel:
    settings = settings or get_settings()
    model = {
        "main": settings.llm_model_main,
        "small": settings.llm_model_small,
        "safety": settings.safety_model,
        "judge": settings.judge_model,
    }[role]
    provider = model.split(":", 1)[0]

    kwargs: dict = {"temperature": 0, "max_retries": 3}  # retries back off on 429 rate limits
    if role == "safety":
        # A short verdict; little reasoning needed. Retry: per-minute limits reset in seconds,
        # and a guard that gives up instantly under load would let attacks through
        kwargs.update(max_retries=3, max_tokens=800, reasoning_effort="low")
    if role == "judge":
        # Grades eval answers: a verdict plus a short claim list. Patient retries: evals aren't
        # interactive, so waiting out a per-minute limit is fine
        kwargs.update(max_retries=5, max_tokens=2000, reasoning_effort="low")
    if role == "small":
        # Fail fast: the agent falls back to the main model (a daily-limit 429 can mean waiting
        # minutes inside the client's retry loop)
        kwargs["max_retries"] = 0
        kwargs["max_tokens"] = settings.llm_small_max_tokens
        if settings.llm_small_reasoning_effort:
            kwargs["reasoning_effort"] = settings.llm_small_reasoning_effort
    if provider == "groq":
        if settings.groq_api_key is None:
            raise RuntimeError("GROQ_API_KEY is not set in .env")
        kwargs["api_key"] = settings.groq_api_key.get_secret_value()
    return init_chat_model(model, **kwargs)
