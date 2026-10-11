"""Embedding model factory. Change provider or model in .env; no code changes needed.

Every embedder is a LangChain `Embeddings`: `embed_documents(texts)` for chunks and
`embed_query(text)` for questions (Cohere embeds the two differently on purpose).
"""

from langchain_core.embeddings import DeterministicFakeEmbedding, Embeddings

from app.config import Settings, get_settings
from app.db.models import EMBED_DIM


def embed_model_id(settings: Settings | None = None) -> str:
    """Stored on every chunk, so vectors from different models are never mixed."""
    settings = settings or get_settings()
    return f"{settings.embed_provider}:{settings.embed_model}"


def get_embedder(settings: Settings | None = None) -> Embeddings:
    settings = settings or get_settings()
    provider = settings.embed_provider

    if provider == "cohere":
        if settings.cohere_api_key is None:
            raise RuntimeError("COHERE_API_KEY is not set in .env")
        from langchain_cohere import CohereEmbeddings

        return CohereEmbeddings(
            model=settings.embed_model,
            # Pass the raw string: langchain-cohere turns a SecretStr into its masked text
            # ("**********"), which Cohere rejects with 401. Never log this value.
            cohere_api_key=settings.cohere_api_key.get_secret_value(),
            max_retries=5,  # backs off and retries on rate limits (429) and network errors
        )
    if provider == "fake":
        # Tests and offline runs: same text -> same vector, no API calls, no meaning
        return DeterministicFakeEmbedding(size=EMBED_DIM)
    raise ValueError(f"Unknown EMBED_PROVIDER {provider!r} (supported: cohere, fake)")


def embed_queries(
    embedder: Embeddings, queries: list[str], batch_size: int = 96
) -> list[list[float]]:
    """Embed many questions with as few API calls as possible (used by evals).

    `embed_query` is one call per question; Cohere can embed up to 96 questions per call as
    long as they are marked as queries (input_type="search_query"), not documents.
    """
    batch_embed = getattr(embedder, "embed", None)
    if batch_embed is None:  # providers without a batch query API
        return [embedder.embed_query(q) for q in queries]
    vectors: list[list[float]] = []
    for start in range(0, len(queries), batch_size):
        vectors += batch_embed(queries[start : start + batch_size], input_type="search_query")
    return vectors
