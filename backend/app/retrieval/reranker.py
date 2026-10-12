"""Rerankers: score how well each candidate chunk answers the question.

Unlike embeddings (question and chunk embedded separately), a reranker is a cross-encoder: it
reads the question and the chunk together, so it judges relevance much more precisely. It is
slower, so it only re-orders the few candidates that search already found.
"""

import re
import time
from typing import Protocol

from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential,
)

from app.config import Settings, get_settings


class Reranker(Protocol):
    model: str

    def rerank(self, query: str, texts: list[str]) -> list[tuple[int, float]]:
        """(index into texts, relevance 0..1) for every text, best first."""
        ...


def _is_transient(exc: BaseException) -> bool:
    """Rate limits, server errors, network drops and timeouts are worth retrying (briefly); a bad
    key is not."""
    import httpx

    status = getattr(exc, "status_code", None)
    return status in (429, 500, 502, 503, 504) or isinstance(
        exc, (ConnectionError, TimeoutError, httpx.TransportError)
    )


class RerankerUnavailable(RuntimeError):
    """The reranker failed recently; callers fall back to search order without waiting."""


class CohereReranker:
    COOLDOWN_S = 300  # after a failure, skip the reranker this long before trying it again

    def __init__(self, api_key: str, model: str, timeout_s: float = 8.0, clock=time.monotonic):
        import cohere

        self.model = f"cohere:{model}"
        self._name = model
        # A timeout on every call: without one, a stuck request blocks the customer's answer
        # (this happened: rerank-v3.5 stopped responding and one question waited 30+ minutes)
        self._client = cohere.ClientV2(api_key=api_key, timeout=timeout_s)
        self._clock = clock
        self._down_until = 0.0

    def rerank(self, query: str, texts: list[str]) -> list[tuple[int, float]]:
        """Circuit breaker: once the reranker has failed, every question would otherwise wait
        out the same timeouts. Fail instantly for a few minutes instead, then try again."""
        if self._clock() < self._down_until:
            raise RerankerUnavailable(f"{self.model} failed recently; retrying it later")
        try:
            return self._rerank(query, texts)
        except Exception:
            self._down_until = self._clock() + self.COOLDOWN_S
            raise

    @retry(
        # Free trial keys allow only a few rerank calls per minute: wait and retry on 429, but
        # give up within seconds so the caller can fall back instead of keeping the customer waiting
        retry=retry_if_exception(_is_transient),
        wait=wait_exponential(multiplier=2, min=2, max=8),
        stop=stop_after_attempt(4) | stop_after_delay(12),
        reraise=True,
    )
    def _rerank(self, query: str, texts: list[str]) -> list[tuple[int, float]]:
        if not texts:
            return []
        response = self._client.rerank(model=self._name, query=query, documents=texts)
        return [(r.index, float(r.relevance_score)) for r in response.results]


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
        return CohereReranker(
            settings.cohere_api_key.get_secret_value(), settings.rerank_model,
            timeout_s=settings.rerank_timeout_s,
        )  # fmt: skip
    if settings.rerank_provider == "overlap":
        return OverlapReranker()
    raise ValueError(
        f"Unknown RERANK_PROVIDER {settings.rerank_provider!r} (supported: cohere, overlap)"
    )
