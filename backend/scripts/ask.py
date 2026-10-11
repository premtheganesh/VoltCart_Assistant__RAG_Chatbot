"""Show what retrieval finds for a question, stage by stage (no LLM yet).

make ask q="can I swim with the stride earbuds?"
make ask q="IPX4" mode=keyword
"""

import argparse
import textwrap

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_engine
from app.llm.embeddings import get_embedder
from app.retrieval.reranker import get_reranker
from app.retrieval.retriever import MODES, Retriever


def rank(value: int | None) -> str:
    return f"#{value}" if value else "-"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--mode", choices=MODES, default="hybrid_rerank")
    parser.add_argument("-k", type=int, default=5, help="chunks to show")
    parser.add_argument("--product", action="append", help="only chunks about this SKU")
    args = parser.parse_args()

    settings = get_settings()
    with Session(get_engine()) as session:
        retriever = Retriever(
            session,
            get_embedder(settings) if args.mode != "keyword" else None,
            get_reranker(settings) if args.mode == "hybrid_rerank" else None,
            settings,
        )
        result = retriever.retrieve(args.question, args.mode, top_k=args.k, products=args.product)

    print(f"\nQ: {result.query}   [mode: {result.mode}, {result.candidates} candidates]")
    print("timings (ms): " + ", ".join(f"{k} {v}" for k, v in result.timings_ms.items()))
    if result.passed_gate is not None:
        verdict = (
            "PASS: answer" if result.passed_gate else "FAIL: say 'I don't know' + offer a human"
        )
        gate = f"top score {result.top_score:.3f} vs {settings.min_relevance}"
        print(f"relevance gate: {gate} -> {verdict}")
    print()
    for i, c in enumerate(result.chunks, start=1):
        page = f", p.{c.page}" if c.page else ""
        print(f"{i}. [{c.score:.3f}] {c.heading}")
        print(
            f"   {c.file_name}{page} | vector {rank(c.vector_rank)}, keyword {rank(c.keyword_rank)}"
        )
        print(textwrap.indent(textwrap.shorten(c.content, 220), "   "))


if __name__ == "__main__":
    main()
