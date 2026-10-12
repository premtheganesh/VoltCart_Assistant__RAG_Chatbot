"""Retrieval: fusion, keyword terms, reranking, the relevance gate and the eval metrics.

Integration tests ingest documents with a fake embedder inside a rolled-back transaction and
rerank by word overlap, so they make no API calls and leave the database unchanged.
"""

import shutil

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from sqlalchemy import delete

from app.config import PROJECT_ROOT, Settings
from app.db.models import EMBED_DIM, Document
from app.ingestion.pipeline import ingest
from app.llm.embeddings import embed_queries
from app.retrieval.reranker import OverlapReranker, _is_transient, get_reranker
from app.retrieval.retriever import Retriever
from app.retrieval.search import query_terms, reciprocal_rank_fusion
from scripts.eval_retrieval import (
    CachedReranker,
    DiskCache,
    gate_accuracy,
    hit_at,
    recall_at,
    reciprocal_rank,
)
from tests.test_ingest import session  # noqa: F401  (rolled-back DB session fixture)

DOCS = PROJECT_ROOT / "sample_data" / "docs"


# ---------- fusion ----------


def test_rrf_rewards_chunks_found_by_both_searches():
    fused = reciprocal_rank_fusion([[1, 2, 3], [3, 4, 1]], k=60)
    ids = [cid for cid, _ in fused]
    assert ids[:2] == [1, 3], "found by both lists beats found by one"
    assert set(ids) == {1, 2, 3, 4}
    assert fused[0][1] == pytest.approx(1 / 61 + 1 / 63)


def test_rrf_uses_ranks_not_scores_and_breaks_ties_by_id():
    assert reciprocal_rank_fusion([[7], [5]]) == [(5, 1 / 61), (7, 1 / 61)]
    assert reciprocal_rank_fusion([]) == []


# ---------- keyword terms ----------


def test_query_terms_keep_codes_and_drop_duplicates():
    terms = query_terms("Is the AU-STRIDE IPX4? is it, IPX4!")
    assert terms == ["is", "the", "au-stride", "ipx4", "it"]
    assert query_terms("???") == []
    assert len(query_terms("word " * 100 + " ".join(f"w{i}" for i in range(50)))) == 32


# ---------- rerankers ----------


def test_overlap_reranker_orders_by_shared_words():
    order = OverlapReranker().rerank(
        "restocking fee laptop", ["shipping costs", "restocking fee on a laptop", "a fee"]
    )
    assert [i for i, _ in order] == [1, 2, 0]
    assert order[0][1] == 1.0 and order[-1][1] == 0.0


def test_reranker_factory():
    overlap = get_reranker(Settings(_env_file=None, rerank_provider="overlap"))
    assert isinstance(overlap, OverlapReranker)
    with pytest.raises(RuntimeError, match="COHERE_API_KEY"):
        get_reranker(Settings(_env_file=None, rerank_provider="cohere", cohere_api_key=None))
    with pytest.raises(ValueError, match="RERANK_PROVIDER"):
        get_reranker(Settings(_env_file=None, rerank_provider="nope"))


class _HTTPError(Exception):
    def __init__(self, status_code):
        self.status_code = status_code


def test_only_transient_errors_are_retried():
    assert _is_transient(_HTTPError(429)) and _is_transient(_HTTPError(503))
    assert _is_transient(ConnectionError())
    assert not _is_transient(_HTTPError(401)), "a bad key must fail fast, not retry"
    assert not _is_transient(ValueError())


def test_timeouts_are_retried_briefly():
    import httpx

    assert _is_transient(httpx.ReadTimeout("slow")) and _is_transient(httpx.ConnectError("x"))


def test_cohere_reranker_has_a_timeout_and_gives_up_quickly(monkeypatch):
    """A rerank that never answers must not hold the customer for minutes."""
    import httpx

    from app.retrieval import reranker as module

    reranker = module.CohereReranker("key", "rerank-v3.5", timeout_s=7)
    assert reranker._client._client_wrapper.get_timeout() == 7
    calls = []

    def hang(**kwargs):
        calls.append(kwargs)
        raise httpx.ReadTimeout("no answer")

    monkeypatch.setattr(reranker._client, "rerank", hang)
    monkeypatch.setattr(module.CohereReranker._rerank.retry, "sleep", lambda s: None)
    with pytest.raises(httpx.ReadTimeout):
        reranker.rerank("q", ["a", "b"])
    assert 1 < len(calls) <= 4, "a few quick retries, then give up"
    assert calls[0] == {"model": "rerank-v3.5", "query": "q", "documents": ["a", "b"]}


def test_circuit_breaker_skips_a_failing_reranker_then_tries_again(monkeypatch):
    from app.retrieval import reranker as module

    now = [1000.0]
    reranker = module.CohereReranker("key", "rerank-v3.5", clock=lambda: now[0])
    calls = []

    def flaky(**kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("bad response")  # not transient: one call
        return type("R", (), {"results": [type("X", (), {"index": 0, "relevance_score": 0.9})]})

    monkeypatch.setattr(reranker._client, "rerank", flaky)
    with pytest.raises(ValueError):
        reranker.rerank("q", ["a"])
    with pytest.raises(module.RerankerUnavailable):
        reranker.rerank("q", ["a"])  # instant: no call made
    assert len(calls) == 1
    now[0] += module.CohereReranker.COOLDOWN_S
    assert reranker.rerank("q", ["a"]) == [(0, 0.9)], "tried again after the cooldown"


def test_cached_reranker_calls_the_api_once(tmp_path):
    reranker = CachedReranker(OverlapReranker(), DiskCache(tmp_path / "c.sqlite"))
    first = reranker.rerank("fee", ["fee", "other"])
    second = reranker.rerank("fee", ["fee", "other"])
    reranker.rerank("fee", ["other", "fee"])  # different candidates -> new call
    assert first == second and reranker.calls == 2


def test_embed_queries_falls_back_to_one_call_per_query():
    fake = DeterministicFakeEmbedding(size=8)
    assert embed_queries(fake, ["a", "b"]) == [fake.embed_query("a"), fake.embed_query("b")]


# ---------- eval metrics ----------


def test_retrieval_metrics():
    files = ["a.pdf", "b.html", "a.pdf", "c.docx", "d.html"]
    assert hit_at(files, ["b.html"], 1) is False and hit_at(files, ["b.html"], 2) is True
    assert reciprocal_rank(files, ["c.docx"]) == 0.25
    assert reciprocal_rank(files, ["zzz.pdf"]) == 0.0
    assert recall_at(files, ["a.pdf", "zzz.pdf"], 5) == 0.5


def test_gate_accuracy_balances_both_kinds_of_mistake():
    answerable, no_answer = [0.9, 0.8, 0.2], [0.1, 0.4]
    assert gate_accuracy(answerable, no_answer, 0.3) == pytest.approx((2 / 3 + 1 / 2) / 2)
    assert gate_accuracy(answerable, no_answer, 0.5) == pytest.approx((2 / 3 + 1) / 2)


# ---------- retriever (integration) ----------


@pytest.fixture
def retriever(session, tmp_path):  # noqa: F811
    docs = tmp_path / "docs"
    docs.mkdir()
    names = ("returns-and-refunds.html", "shipping-policy.html", "stride-sport-earbuds-manual.pdf")
    for name in names:
        shutil.copy(DOCS / name, docs / name)
    # Start from an empty knowledge base; the transaction is rolled back, so real data returns
    session.execute(delete(Document))
    embedder = DeterministicFakeEmbedding(size=EMBED_DIM)
    ingest(session, embedder, "fake:test", docs, source_root=tmp_path, include_catalog=False)
    settings = Settings(_env_file=None, retrieval_candidates=10, min_relevance=0.5)
    return Retriever(session, embedder, OverlapReranker(), settings)


@pytest.mark.integration
def test_keyword_mode_finds_exact_terms(retriever):
    top = retriever.retrieve("restocking fee", "keyword").chunks[0]
    assert top.heading == "Returns and Refunds > Is there a restocking fee?"
    assert top.keyword_rank is not None and top.vector_rank is None


@pytest.mark.integration
def test_keyword_mode_matches_any_word_not_all(retriever):
    result = retriever.retrieve("restocking fee for my unicorn spaceship", "keyword")
    assert result.chunks, "unmatched words must not wipe out the results"


@pytest.mark.integration
def test_hybrid_rerank_returns_top_k_with_gate(retriever):
    result = retriever.retrieve("is there a restocking fee on returns", "hybrid_rerank", top_k=3)

    assert len(result.chunks) == 3
    assert result.chunks[0].heading == "Returns and Refunds > Is there a restocking fee?"
    scores = [c.rerank_score for c in result.chunks]
    assert scores == sorted(scores, reverse=True)
    assert result.passed_gate is True and result.top_score == scores[0]
    assert {"embed", "vector", "keyword", "rerank"} <= result.timings_ms.keys()


class _DownReranker:
    model = "down"

    def rerank(self, query, texts):
        raise TimeoutError("reranker not responding")


@pytest.mark.integration
def test_reranker_outage_falls_back_to_search_order(retriever):
    healthy = retriever.retrieve("is there a restocking fee on returns", "hybrid", top_k=3)
    retriever.reranker = _DownReranker()
    result = retriever.retrieve("is there a restocking fee on returns", "hybrid_rerank", top_k=3)
    assert [c.chunk_id for c in result.chunks] == [c.chunk_id for c in healthy.chunks]
    assert result.top_score is None, "no relevance score: visible to logs and evals"
    assert result.passed_gate is True, "the customer still gets an answer from the sources"


@pytest.mark.integration
def test_gate_stops_questions_nothing_answers(retriever):
    result = retriever.retrieve("quantum zebra marmalade", "hybrid_rerank")
    assert result.passed_gate is False and result.top_score < 0.5


@pytest.mark.integration
def test_product_filter_limits_results(retriever):
    result = retriever.retrieve("battery and charging", "hybrid", top_k=20, products=["AU-STRIDE"])
    assert result.chunks and all("AU-STRIDE" in c.products for c in result.chunks)


@pytest.mark.integration
def test_doc_type_filter_limits_results(retriever):
    result = retriever.retrieve("returns", "hybrid", top_k=20, doc_types=["manual"])
    assert result.chunks and all(c.doc_type == "manual" for c in result.chunks)


@pytest.mark.integration
def test_hybrid_records_both_ranks(retriever):
    result = retriever.retrieve("restocking fee", "hybrid", top_k=40)
    both = [c for c in result.chunks if c.vector_rank and c.keyword_rank]
    assert both, "hybrid keeps each chunk's rank in both lists, for debugging"
