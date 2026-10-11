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

Role = Literal["main", "small"]


def get_chat_model(role: Role, settings: Settings | None = None) -> BaseChatModel:
    settings = settings or get_settings()
    model = settings.llm_model_main if role == "main" else settings.llm_model_small
    provider = model.split(":", 1)[0]

    kwargs: dict = {"temperature": 0, "max_retries": 3}  # retries back off on 429 rate limits
    if role == "small":
        kwargs["max_tokens"] = settings.llm_small_max_tokens
        if settings.llm_small_reasoning_effort:
            kwargs["reasoning_effort"] = settings.llm_small_reasoning_effort
    if provider == "groq":
        if settings.groq_api_key is None:
            raise RuntimeError("GROQ_API_KEY is not set in .env")
        kwargs["api_key"] = settings.groq_api_key.get_secret_value()
    return init_chat_model(model, **kwargs)
