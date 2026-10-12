"""Application settings, loaded from environment variables and the project-root .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    postgres_user: str = "voltcart"
    postgres_password: SecretStr = SecretStr("voltcart_dev_password")
    postgres_db: str = "voltcart"
    postgres_host: str = "localhost"
    postgres_port: int = 5433

    # LLM
    groq_api_key: SecretStr | None = None
    # "provider:model". Main writes answers; small routes and rewrites (fast, cheap)
    llm_model_main: str = "groq:openai/gpt-oss-120b"
    llm_model_small: str = "groq:openai/gpt-oss-20b"
    # Router/rewriter output is a tiny JSON object: cap it, and limit hidden "thinking" tokens
    # (model-specific values: gpt-oss "low"/"medium"/"high", qwen "none"/"default")
    llm_small_max_tokens: int = 512
    llm_small_reasoning_effort: str | None = None

    # Embeddings + rerank
    cohere_api_key: SecretStr | None = None
    embed_provider: str = "cohere"
    embed_model: str = "embed-multilingual-v3.0"
    embed_batch_size: int = 96  # Cohere's maximum texts per embed call
    rerank_provider: str = "cohere"
    rerank_model: str = "rerank-v3.5"

    # Retrieval
    retrieval_candidates: int = 20  # taken from each of vector and keyword search
    retrieval_top_k: int = 5  # chunks handed to the LLM
    rrf_k: int = 60  # Reciprocal Rank Fusion constant (60 is the standard value)
    min_relevance: float = 0.15  # relevance gate: below this rerank score, answer "I don't know"

    # Ingestion
    docs_dir: str = "sample_data/docs"
    chunk_max_tokens: int = 600
    chunk_overlap_tokens: int = 80

    # Observability
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    # Guardrails
    safety_model: str = "groq:openai/gpt-oss-safeguard-20b"  # input check, always on
    prompt_guard_model: str = "meta-llama/llama-prompt-guard-2-86m"  # backup injection check
    output_guard: bool = False  # also check the bot's replies (one more call per answer)
    grounding_check: bool = False  # L2: a judge verifies each answer against its sources

    # Agent
    history_messages: int = 10  # earlier messages the LLM sees (all are stored)

    # App
    app_env: str = "dev"
    log_level: str = "INFO"

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def psycopg_url(self) -> str:
        """Plain libpq URL (no SQLAlchemy driver prefix), for LangGraph's checkpointer."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:"
            f"{self.postgres_password.get_secret_value()}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
