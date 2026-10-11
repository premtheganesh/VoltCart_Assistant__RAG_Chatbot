"""Retrieval eval: does the right document reach the top 5 for each golden question?

    make eval-retrieval                 # all four modes, writes evals/reports/retrieval.md

Compares vector, keyword, hybrid and hybrid + rerank on the same questions, and calibrates
the relevance gate on questions the documents cannot answer. Query embeddings and rerank
results are cached on disk (evals/.cache), so re-running costs no API calls unless the
questions, chunks or models change.
"""

import argparse
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median

from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT, get_settings
from app.db.session import get_engine
from app.llm.embeddings import embed_model_id, embed_queries, get_embedder
from app.retrieval.reranker import Reranker, get_reranker
from app.retrieval.retriever import MODES, RetrievalResult, Retriever

GOLDEN = PROJECT_ROOT / "evals" / "datasets" / "golden.jsonl"
CACHE = PROJECT_ROOT / "evals" / ".cache" / "retrieval.sqlite"
REPORT = PROJECT_ROOT / "evals" / "reports" / "retrieval.md"
K = 5
GATE_THRESHOLDS = [round(0.05 * i, 2) for i in range(1, 20)]


# ---------- metrics ----------


def hit_at(files: list[str], expected: list[str], k: int) -> bool:
    """Did any expected document appear in the top k chunks?"""
    return any(f in expected for f in files[:k])


def reciprocal_rank(files: list[str], expected: list[str], k: int = K) -> float:
    """1 / rank of the first chunk from an expected document (0 if not in the top k)."""
    return next((1 / i for i, f in enumerate(files[:k], start=1) if f in expected), 0.0)


def recall_at(files: list[str], expected: list[str], k: int) -> float:
    """Share of the expected documents found in the top k (matters for multi-source answers)."""
    return len(set(files[:k]) & set(expected)) / len(expected)


def gate_accuracy(answerable: list[float], no_answer: list[float], threshold: float) -> float:
    """Balanced accuracy: answerable questions pass the gate, unanswerable ones are stopped."""
    passed = mean(s >= threshold for s in answerable) if answerable else 1.0
    stopped = mean(s < threshold for s in no_answer) if no_answer else 1.0
    return (passed + stopped) / 2


# ---------- cache ----------


class DiskCache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT)")

    @staticmethod
    def key(*parts: str) -> str:
        return hashlib.sha256("\x00".join(parts).encode()).hexdigest()

    def get(self, key: str):
        row = self.db.execute("SELECT value FROM cache WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set(self, key: str, value) -> None:
        self.db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?)", (key, json.dumps(value)))
        self.db.commit()


class CachedReranker:
    def __init__(self, inner: Reranker, cache: DiskCache):
        self.inner, self.cache, self.model = inner, cache, inner.model
        self.calls = 0

    def rerank(self, query: str, texts: list[str]) -> list[tuple[int, float]]:
        key = self.cache.key("rerank", self.model, query, *texts)
        if (hit := self.cache.get(key)) is not None:
            return [tuple(x) for x in hit]
        self.calls += 1
        result = self.inner.rerank(query, texts)
        self.cache.set(key, result)
        return result


def cached_query_vectors(embedder, model: str, questions: list[str], cache: DiskCache):
    keys = [cache.key("query", model, q) for q in questions]
    vectors = {k: v for k in keys if (v := cache.get(k)) is not None}
    missing = [(k, q) for k, q in zip(keys, questions, strict=True) if k not in vectors]
    if missing:
        for (k, _), v in zip(
            missing, embed_queries(embedder, [q for _, q in missing]), strict=True
        ):
            cache.set(k, v)
            vectors[k] = v
    return [vectors[k] for k in keys], len(missing)


# ---------- run ----------


@dataclass
class Row:
    item: dict
    result: RetrievalResult

    @property
    def files(self) -> list[str]:
        return [c.file_name for c in self.result.chunks]


def load_items() -> tuple[list[dict], list[dict]]:
    golden = [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]
    standalone = [i for i in golden if "history" not in i]  # follow-ups need query rewriting
    answerable = [
        i for i in standalone
        if i["expected_sources"] and i["category"] not in ("order", "handoff", "smalltalk")
    ]  # fmt: skip
    no_answer = [
        i for i in standalone
        if i["category"] == "off_topic"
        or (i["behavior"] == "not_in_docs" and not i["expected_sources"])
    ]  # fmt: skip
    return answerable, no_answer


def summarize(rows: list[Row]) -> dict[str, float]:
    exp = [r.item["expected_sources"] for r in rows]
    return {
        "hit@1": mean(hit_at(r.files, e, 1) for r, e in zip(rows, exp, strict=True)),
        "hit@3": mean(hit_at(r.files, e, 3) for r, e in zip(rows, exp, strict=True)),
        "hit@5": mean(hit_at(r.files, e, 5) for r, e in zip(rows, exp, strict=True)),
        "MRR@5": mean(reciprocal_rank(r.files, e) for r, e in zip(rows, exp, strict=True)),
        "recall@5": mean(recall_at(r.files, e, 5) for r, e in zip(rows, exp, strict=True)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
    parser.add_argument("--min-hit", type=float, default=0.85, help="fail below this hit@5")
    args = parser.parse_args()

    settings = get_settings()
    answerable, no_answer = load_items()
    cache = DiskCache(CACHE)
    embedder = get_embedder(settings)
    model = embed_model_id(settings)
    questions = [i["question"] for i in answerable + no_answer]
    vectors, embedded = cached_query_vectors(embedder, model, questions, cache)
    vector_of = dict(zip(questions, vectors, strict=True))
    reranker = (
        CachedReranker(get_reranker(settings), cache) if "hybrid_rerank" in args.modes else None
    )

    results: dict[str, list[Row]] = {}
    gate_rows: list[Row] = []
    with Session(get_engine()) as session:
        retriever = Retriever(session, embedder, reranker, settings)
        for mode in args.modes:
            results[mode] = []
            for n, item in enumerate(answerable + (no_answer if mode == "hybrid_rerank" else [])):
                q = item["question"]
                print(f"\r{mode:14} {n + 1}/{len(answerable) + len(no_answer)}", end="", flush=True)
                row = Row(item, retriever.retrieve(q, mode, top_k=K, query_vector=vector_of[q]))
                (results[mode] if item in answerable else gate_rows).append(row)
    print()

    lines = render_report(results, gate_rows, settings, answerable, no_answer)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    calls = embedded and 1 + (embedded - 1) // 96
    print(f"\nAPI calls this run: {calls} embed, {reranker.calls if reranker else 0} rerank")
    print(f"Report written to {REPORT.relative_to(PROJECT_ROOT)}")

    best = "hybrid_rerank" if "hybrid_rerank" in results else args.modes[-1]
    if summarize(results[best])["hit@5"] < args.min_hit:
        sys.exit(f"FAIL: {best} hit@5 is below the target {args.min_hit}")


def _stats_row(label: str, scores: list[float]) -> str:
    stats = (min(scores), median(scores), max(scores))
    return f"| {label} | {len(scores)} | " + " | ".join(f"{v:.3f}" for v in stats) + " |"


def render_report(results, gate_rows, settings, answerable, no_answer) -> list[str]:
    lines = [
        "# Retrieval eval",
        "",
        f"Run {datetime.now(UTC):%Y-%m-%d %H:%M} UTC on {len(answerable)} answerable golden "
        f"questions (follow-ups excluded until query rewriting in Phase 5). Embeddings "
        f"`{embed_model_id(settings)}`, rerank `{settings.rerank_model}`, "
        f"{settings.retrieval_candidates} candidates per search, RRF k={settings.rrf_k}.",
        "",
        "| Mode | hit@1 | hit@3 | hit@5 | MRR@5 | recall@5 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for mode, rows in results.items():
        m = summarize(rows)
        lines.append(f"| {mode} | " + " | ".join(f"{v:.2f}" for v in m.values()) + " |")

    best = "hybrid_rerank" if "hybrid_rerank" in results else list(results)[-1]
    rows = results[best]
    lines += ["", f"## hit@5 by category ({best})", "", "| Category | Questions | hit@5 |",
              "| --- | --- | --- |"]  # fmt: skip
    for category in sorted({r.item["category"] for r in rows}):
        sub = [r for r in rows if r.item["category"] == category]
        lines.append(f"| {category} | {len(sub)} | {summarize(sub)['hit@5']:.2f} |")

    if gate_rows and "hybrid_rerank" in results:
        good = [r.result.top_score for r in results["hybrid_rerank"]]
        bad = [r.result.top_score for r in gate_rows]
        best_t = max(GATE_THRESHOLDS, key=lambda t: (gate_accuracy(good, bad, t), -t))
        lines += [
            "",
            "## Relevance gate (top rerank score)",
            "",
            "| Questions | Count | min | median | max |",
            "| --- | --- | --- | --- | --- |",
            _stats_row("answerable", good),
            _stats_row("not answerable", bad),
            "",
            f"Gate accuracy at MIN_RELEVANCE={settings.min_relevance}: "
            f"{gate_accuracy(good, bad, settings.min_relevance):.2f} "
            f"(answerable passed {mean(s >= settings.min_relevance for s in good):.2f}, "
            f"unanswerable stopped {mean(s < settings.min_relevance for s in bad):.2f}). "
            f"Highest accuracy on this small set: {best_t} "
            f"({gate_accuracy(good, bad, best_t):.2f}); "
            "check the lowest-scoring answerable questions below before raising the gate.",
        ]
        lines += [
            "",
            "| Lowest-scoring answerable question | Top score | Top chunk |",
            "| --- | --- | --- |",
        ]
        for r in sorted(results["hybrid_rerank"], key=lambda r: r.result.top_score)[:5]:
            top = r.result.chunks[0].heading
            lines.append(f"| {r.item['question']} | {r.result.top_score:.3f} | {top} |")
        lines += ["", "| Not-answerable question | Top score | Top chunk |", "| --- | --- | --- |"]
        for r in gate_rows:
            top = r.result.chunks[0].heading if r.result.chunks else "-"
            lines.append(f"| {r.item['question']} | {r.result.top_score:.3f} | {top} |")

    misses = [r for r in rows if not hit_at(r.files, r.item["expected_sources"], K)]
    lines += ["", f"## Misses ({best}, not in top {K})", ""]
    if not misses:
        lines.append("None.")
    else:
        lines += ["| Id | Question | Expected | Got (top 3) |", "| --- | --- | --- | --- |"]
        for r in misses:
            got = "; ".join(c.heading for c in r.result.chunks[:3])
            exp = ", ".join(r.item["expected_sources"])
            lines.append(f"| {r.item['id']} | {r.item['question']} | {exp} | {got} |")
    return lines


if __name__ == "__main__":
    main()
