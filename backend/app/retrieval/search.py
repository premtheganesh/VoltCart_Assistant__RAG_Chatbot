"""The two first-stage searches, and the fusion that merges them.

- Vector search: chunks whose embedding points the same way as the question's (cosine).
- Keyword search: chunks containing the question's words (Postgres full-text, OR-matched).
- Reciprocal Rank Fusion: merges the two ranked lists using ranks only, so the two very
  different score scales (cosine 0..1, ts_rank 0..~1) never have to be compared.
"""

import re
from collections import defaultdict
from functools import reduce

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document

TERM = re.compile(r"\w[\w-]*")
MAX_TERMS = 32


def _filtered(stmt: Select, products: list[str] | None, doc_types: list[str] | None) -> Select:
    if products:
        stmt = stmt.where(Chunk.products.overlap(products))
    if doc_types:
        stmt = stmt.join(Document).where(Document.doc_type.in_(doc_types))
    return stmt


def vector_search(
    session: Session,
    query_vector: list[float],
    k: int,
    products: list[str] | None = None,
    doc_types: list[str] | None = None,
) -> list[tuple[int, float]]:
    """(chunk id, cosine similarity) best first. Uses the HNSW index."""
    distance = Chunk.embedding.cosine_distance(query_vector)
    stmt = select(Chunk.id, (1 - distance).label("score")).order_by(distance).limit(k)
    return [
        (cid, float(score)) for cid, score in session.execute(_filtered(stmt, products, doc_types))
    ]


def query_terms(query: str) -> list[str]:
    """Words of the question, lowercased, de-duplicated, in order (codes like AU-STRIDE kept)."""
    seen: dict[str, None] = {}
    for term in TERM.findall(query.lower()):
        seen.setdefault(term)
    return list(seen)[:MAX_TERMS]


def keyword_search(
    session: Session,
    query: str,
    k: int,
    products: list[str] | None = None,
    doc_types: list[str] | None = None,
) -> list[tuple[int, float]]:
    """(chunk id, ts_rank) best first. Uses the GIN index.

    Terms are OR-ed: a chunk matching some of the words still counts, and matching more ranks
    higher. (Postgres' plainto_tsquery ANDs every word, so one unmatched word returns nothing.)
    Stop words ("the", "can") are dropped and words are stemmed ("fees" -> "fee").
    """
    terms = query_terms(query)
    if not terms:
        return []
    tsquery = reduce(
        lambda a, b: a.op("||")(b), (func.plainto_tsquery("english", t) for t in terms)
    )
    # Normalization 1 divides by 1 + log(length), so long tables don't win just by being long
    rank = func.ts_rank(Chunk.tsv, tsquery, 1)
    stmt = (
        select(Chunk.id, rank.label("score"))
        .where(Chunk.tsv.op("@@")(tsquery))
        .order_by(rank.desc(), Chunk.id)
        .limit(k)
    )
    return [
        (cid, float(score)) for cid, score in session.execute(_filtered(stmt, products, doc_types))
    ]


def reciprocal_rank_fusion(rankings: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    """score(chunk) = sum over lists of 1 / (k + rank). Found high in both lists = top.

    k = 60 (from the original RRF paper) keeps one list's #1 from dominating the other's.
    """
    scores: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] += 1 / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))
