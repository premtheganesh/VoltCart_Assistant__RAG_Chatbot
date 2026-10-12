"""Draft new golden questions from the knowledge base, for a human to review.

    make synthetic                 # 10 drafts -> evals/datasets/synthetic_candidates.jsonl
    make synthetic args="--n 20 --seed 7"

Each draft comes from one random passage: a question a customer might ask, the answer from that
passage, and key phrases copied word for word from it. Drafts are NOT used by any eval until
someone reviews them and copies the good ones into golden.jsonl (with the next free id).
Why review: a model writing its own test questions repeats its own blind spots, and an
unchecked wrong "expected answer" silently teaches you the wrong thing. Uses the judge model
only (no Cohere calls).
"""

import argparse
import json
import random
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT, get_settings
from app.db.models import Chunk, Document
from app.db.session import get_engine
from app.llm.chat import get_chat_model
from scripts.eval_answers import with_retries
from scripts.eval_retrieval import GOLDEN

OUT = PROJECT_ROOT / "evals" / "datasets" / "synthetic_candidates.jsonl"
STYLES = [
    "short and casual, lowercase", "polite and complete", "with a small typo",
    "as a worried customer", "comparing two options", "asking about an edge case",
]  # fmt: skip

PROMPT = """You write test questions for VoltCart's customer-support chatbot. Given one passage \
from VoltCart's documents, write ONE question a real customer might type whose answer is in \
the passage, in the requested style. Then answer it using ONLY the passage. key_phrases: 2-3 \
short phrases (2-6 words) copied EXACTLY, character for character, from the passage, that a \
correct answer must mention. category: product_info for product features, setup or specs; \
policy for shipping, returns, warranty, payment, account or support rules."""


class Draft(BaseModel):
    question: str
    expected_answer: str
    key_phrases: list[str]
    category: Literal["product_info", "policy"]


def pick_chunks(session: Session, n: int, seed: int) -> list[tuple[Chunk, Document]]:
    rows = session.execute(
        select(Chunk, Document).join(Document)
        .where(Document.doc_type != "product", Chunk.token_count >= 80)
        .order_by(Chunk.id)
    ).all()  # fmt: skip
    return random.Random(seed).sample(rows, min(n, len(rows)))


def is_duplicate(question: str, existing: list[str]) -> bool:
    words = set(question.lower().split())
    return any(len(words & set(e.lower().split())) / max(len(words), 1) > 0.8 for e in existing)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    settings = get_settings()
    writer = get_chat_model("judge", settings).with_structured_output(
        Draft, method="json_schema", strict=True
    )
    existing = [json.loads(line)["question"] for line in GOLDEN.read_text().splitlines() if line]
    styles = random.Random(args.seed)
    drafts, skipped = [], []
    with Session(get_engine()) as session:
        for n, (chunk, doc) in enumerate(pick_chunks(session, args.n, args.seed), start=1):
            style = styles.choice(STYLES)
            passage = f"[{doc.title} > {chunk.heading}]\n{chunk.content}"
            print(f"[{n}/{args.n}] {doc.title} > {chunk.heading[:60]}", flush=True)
            draft = with_retries(lambda p=passage, s=style: writer.invoke(
                [SystemMessage(PROMPT), HumanMessage(f"Style: {s}\n\nPassage:\n{p}")]))  # fmt: skip
            if draft is None:
                skipped.append((chunk.id, "generation failed"))
                continue
            # Keep only phrases that really are in the passage: no invented "facts"
            phrases = [p for p in draft.key_phrases[:3] if p.lower() in chunk.content.lower()]
            if not phrases:
                skipped.append((chunk.id, "key phrases not in the passage"))
                continue
            if is_duplicate(draft.question, existing + [d["question"] for d in drafts]):
                skipped.append((chunk.id, "too similar to an existing question"))
                continue
            drafts.append({
                "id": f"s{len(drafts) + 1:03d}", "status": "candidate",
                "category": draft.category, "route": "product_info", "behavior": "answer",
                "question": draft.question, "expected_answer": draft.expected_answer,
                "expected_sources": [doc.source.rsplit("/", 1)[-1]],
                "must_include": phrases, "must_not_include": [],
                "tags": ["synthetic"], "source_passage": f"{doc.title} > {chunk.heading}",
            })  # fmt: skip
    OUT.write_text("".join(json.dumps(d) + "\n" for d in drafts))
    print(f"\n{len(drafts)} drafts written to {OUT.relative_to(PROJECT_ROOT)}; skipped "
          f"{len(skipped)}: {skipped}")  # fmt: skip
    print("Review them: keep the realistic, correct ones by copying them into golden.jsonl.")


if __name__ == "__main__":
    main()
