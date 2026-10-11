"""Rerankers: score how well each candidate chunk answers the question.

Unlike embeddings (question and chunk embedded separately), a reranker is a cross-encoder: it
reads the question and the chunk together, so it judges relevance much more precisely. It is
slower, so it only re-orders the few candidates that search already found.
"""

import re
from typing import Protocol

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import Settings, get_settings


class Reranker(Protocol):
    model: str

    def rerank(self, query: str, texts: list[str]) -> list[tuple[int, float]]:
        """(index into texts, relevance 0..1) for every text, best first."""
        ...


def _is_transient(exc: BaseException) -> bool:
    """Rate limits, server errors and network drops are worth retrying; a bad key is not."""
    status = getattr(exc, "status_code", None)
    return status in (429, 500, 502, 503, 504) or isinstance(exc, (ConnectionError, TimeoutError))


class CohereReranker:
    def __init__(self, api_key: str, model: str):
        from langchain_cohere import CohereRerank

        self.model = f"cohere:{model}"
        self._client = CohereRerank(model=model, cohere_api_key=api_key, top_n=None)

    @retry(
        # Free trial keys allow only a few rerank calls per minute: wait and retry on 429
        retry=retry_if_exception(_is_transient),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        stop=stop_after_attempt(6),
        reraise=True,
    )
    def rerank(self, query: str, texts: list[str]) -> list[tuple[int, float]]:
        if not texts:
            return []
        results = self._client.rerank(texts, query, top_n=None)
        return [(r["index"], float(r["relevance_score"])) for r in results]


WORD = re.compile(r"\w+")


class OverlapReranker:
    """Offline stand-in for tests: share of question words found in the text. No meaning."""

    model = "overlap:v1"

    def rerank(self, query: str, texts: list[str]) -> list[tuple[int, float]]:
        terms = {w for w in WORD.findall(query.lower()) if len(w) > 2}
        scores = []
        for i, text in enumerate(texts):
            words = set(WORD.findall(text.lower()))
            scores.append((i, len(terms & words) / len(terms) if terms else 0.0))
        return sorted(scores, key=lambda s: (-s[1], s[0]))


def get_reranker(settings: Settings | None = None) -> Reranker:
    settings = settings or get_settings()
    if settings.rerank_provider == "cohere":
        if settings.cohere_api_key is None:
            raise RuntimeError("COHERE_API_KEY is not set in .env")
        return CohereReranker(settings.cohere_api_key.get_secret_value(), settings.rerank_model)
    if settings.rerank_provider == "overlap":
        return OverlapReranker()
    raise ValueError(
        f"Unknown RERANK_PROVIDER {settings.rerank_provider!r} (supported: cohere, overlap)"
    )
