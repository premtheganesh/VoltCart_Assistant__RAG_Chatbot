"""Retrieval pipeline: question -> the few chunks the LLM should answer from.

    question ─┬─► vector search  (top 20) ─┐
              │                            ├─► RRF ─► rerank ─► top 5 ─► relevance gate
              └─► keyword search (top 20) ─┘

Each mode stops at a different point, so the eval can measure what every stage adds.
"""

import time
from dataclasses import dataclass, field
from typing import Literal

from langchain_core.embeddings import Embeddings
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import Chunk, Document
from app.retrieval.reranker import Reranker
from app.retrieval.search import keyword_search, reciprocal_rank_fusion, vector_search

Mode = Literal["vector", "keyword", "hybrid", "hybrid_rerank"]
MODES: tuple[Mode, ...] = ("vector", "keyword", "hybrid", "hybrid_rerank")


@dataclass
class RetrievedChunk:
    chunk_id: int
    source: str
    title: str
    doc_type: str
    url: str | None
    heading: str
    content: str
    page: int | None
    products: list[str]
    score: float  # the score the final order is based on (rerank, RRF, cosine or ts_rank)
    vector_rank: int | None = None
    keyword_rank: int | None = None
    rerank_score: float | None = None

    @property
    def text(self) -> str:
        return f"{self.heading}\n\n{self.content}"

    @property
    def file_name(self) -> str:
        return self.source.rsplit("/", 1)[-1]


@dataclass
class RetrievalResult:
    query: str
    mode: Mode
    chunks: list[RetrievedChunk]
    candidates: int = 0
    # Relevance gate: only meaningful after reranking (None for other modes)
    top_score: float | None = None
    passed_gate: bool | None = None
    timings_ms: dict[str, float] = field(default_factory=dict)


class Retriever:
    def __init__(
        self,
        session: Session,
        embedder: Embeddings | None,
        reranker: Reranker | None,
        settings: Settings | None = None,
    ):
        self.session = session
        self.embedder = embedder
        self.reranker = reranker
        self.settings = settings or get_settings()

    def retrieve(
        self,
        query: str,
        mode: Mode = "hybrid_rerank",
        *,
        top_k: int | None = None,
        products: list[str] | None = None,
        doc_types: list[str] | None = None,
        query_vector: list[float] | None = None,
    ) -> RetrievalResult:
        s = self.settings
        top_k = top_k or s.retrieval_top_k
        n = s.retrieval_candidates
        timings: dict[str, float] = {}

        def timed(name: str, fn):
            start = time.perf_counter()
            value = fn()
            timings[name] = round((time.perf_counter() - start) * 1000, 1)
            return value

        vector_hits: list[tuple[int, float]] = []
        keyword_hits: list[tuple[int, float]] = []
        if mode != "keyword":
            if query_vector is None:
                query_vector = timed("embed", lambda: self.embedder.embed_query(query))
            vector_hits = timed(
                "vector", lambda: vector_search(self.session, query_vector, n, products, doc_types)
            )
        if mode != "vector":
            keyword_hits = timed(
                "keyword", lambda: keyword_search(self.session, query, n, products, doc_types)
            )

        vector_rank = {cid: i for i, (cid, _) in enumerate(vector_hits, start=1)}
        keyword_rank = {cid: i for i, (cid, _) in enumerate(keyword_hits, start=1)}
        if mode == "vector":
            ranked = vector_hits
        elif mode == "keyword":
            ranked = keyword_hits
        else:
            ranked = reciprocal_rank_fusion(
                [[c for c, _ in vector_hits], [c for c, _ in keyword_hits]], k=s.rrf_k
            )
            if mode == "hybrid_rerank":
                ranked = ranked[:n]  # the reranker only sees the best fused candidates

        chunks = self._load([cid for cid, _ in ranked], dict(ranked), vector_rank, keyword_rank)
        result = RetrievalResult(query=query, mode=mode, chunks=chunks, candidates=len(chunks))

        if mode == "hybrid_rerank" and chunks:
            order = timed("rerank", lambda: self.reranker.rerank(query, [c.text for c in chunks]))
            chunks = [chunks[i] for i, _ in order]
            for chunk, (_, score) in zip(chunks, order, strict=True):
                chunk.rerank_score = chunk.score = score
            result.top_score = chunks[0].score
            result.passed_gate = result.top_score >= s.min_relevance
        elif mode == "hybrid_rerank":
            result.top_score, result.passed_gate = 0.0, False

        result.chunks = chunks[:top_k]
        result.timings_ms = timings
        return result

    def _load(self, ids, scores, vector_rank, keyword_rank) -> list[RetrievedChunk]:
        if not ids:
            return []
        rows = self.session.execute(
            select(Chunk, Document).join(Document).where(Chunk.id.in_(ids))
        ).all()
        by_id = {chunk.id: (chunk, doc) for chunk, doc in rows}
        return [
            RetrievedChunk(
                chunk_id=cid,
                source=doc.source,
                title=doc.title,
                doc_type=doc.doc_type,
                url=doc.url,
                heading=chunk.heading,
                content=chunk.content,
                page=chunk.page,
                products=list(chunk.products),
                score=scores[cid],
                vector_rank=vector_rank.get(cid),
                keyword_rank=keyword_rank.get(cid),
            )
            for cid in ids
            for chunk, doc in [by_id[cid]]
        ]
