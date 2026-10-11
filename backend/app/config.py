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
    llm_model_main: str = "groq:llama-3.3-70b-versatile"
    llm_model_small: str = "groq:llama-3.1-8b-instant"

    # Embeddings + rerank
    cohere_api_key: SecretStr | None = None
    embed_model: str = "embed-multilingual-v3.0"
    rerank_model: str = "rerank-v3.5"

    # Observability
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    # App
    app_env: str = "dev"
    log_level: str = "INFO"

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
