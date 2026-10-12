"""Routing eval: does the router pick the expected route for every golden question?

    make eval-routing        # writes evals/reports/routing.md; target accuracy >= 0.90

Uses only the small LLM (no embeddings or rerank). Results are cached per model + prompt +
conversation, so re-runs are free until the prompt or model changes.
"""

import argparse
import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime

from langchain_core.messages import AIMessage, HumanMessage

from app.config import PROJECT_ROOT, get_settings
from app.graph.agent import make_analyzer
from app.graph.prompts import ROUTER_PROMPT
from app.graph.state import Analysis
from app.llm.chat import get_chat_model
from scripts.eval_common import write_metrics
from scripts.eval_retrieval import GOLDEN, DiskCache

CACHE = PROJECT_ROOT / "evals" / ".cache" / "routing.sqlite"
REPORT = PROJECT_ROOT / "evals" / "reports" / "routing.md"


def messages_of(item: dict) -> list:
    history = [
        HumanMessage(t["content"]) if t["role"] == "user" else AIMessage(t["content"])
        for t in item.get("history", [])
    ]
    return [*history, HumanMessage(item["question"])]


def route_with_retry(analyze, msgs, attempts: int = 4, wait_s: float = 30) -> dict | None:
    """Free-tier limits are per minute: on failure, wait and try again."""
    for attempt in range(1, attempts + 1):
        try:
            return analyze(msgs).model_dump()
        except Exception:
            if attempt < attempts:
                time.sleep(wait_s)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--min-accuracy", type=float, default=0.90)
    args = parser.parse_args()

    settings = get_settings()
    golden = [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]
    analyze = make_analyzer(get_chat_model("small", settings), fallback=False)
    cache = DiskCache(CACHE)

    rows, calls, errors = [], 0, []
    for n, item in enumerate(golden, start=1):
        print(f"\rrouting {n}/{len(golden)}", end="", flush=True)
        msgs = messages_of(item)
        key = cache.key(
            "route", settings.llm_model_small, ROUTER_PROMPT, *(m.content for m in msgs)
        )
        if (hit := cache.get(key)) is None:
            calls += 1
            hit = route_with_retry(analyze, msgs)
            if hit is None:  # never cache or score a failure as an answer
                errors.append(item["id"])
                continue
            cache.set(key, hit)
        rows.append((item, Analysis(**hit)))
    print()
    if errors:
        print(f"{len(errors)} questions failed after retries (rate limit?): {errors}")

    correct = [item["route"] == got.route for item, got in rows]
    accuracy = sum(correct) / len(rows)
    write_metrics("routing", {"accuracy": round(accuracy, 4), "scored": len(rows),
                              "total": len(golden), "not_scored": errors})  # fmt: skip
    lines = [
        "# Routing eval",
        "",
        f"Run {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, router `{settings.llm_model_small}`, "
        f"{len(rows)} golden questions.",
        "",
        f"**Accuracy: {accuracy:.2f}** (target {args.min_accuracy})",
        "",
        "| Expected route | Questions | Correct |",
        "| --- | --- | --- |",
    ]
    totals = Counter(item["route"] for item, _ in rows)
    right = Counter(item["route"] for (item, _), ok in zip(rows, correct, strict=True) if ok)
    for route_name in sorted(totals):
        lines.append(f"| {route_name} | {totals[route_name]} | {right[route_name]} |")

    lines += [
        "",
        "## Wrong routes",
        "",
        "| Id | Question | Expected | Got |",
        "| --- | --- | --- | --- |",
    ]
    for (item, got), ok in zip(rows, correct, strict=True):
        if not ok:
            lines.append(f"| {item['id']} | {item['question']} | {item['route']} | {got.route} |")

    lines += ["", "## Follow-up rewrites", "", "| Id | Question | Rewritten search query |",
              "| --- | --- | --- |"]  # fmt: skip
    for item, got in rows:
        if "history" in item:
            lines.append(f"| {item['id']} | {item['question']} | {got.search_query} |")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nLLM calls this run: {calls}. Report: {REPORT.relative_to(PROJECT_ROOT)}")
    if errors:
        sys.exit(f"FAIL: {len(errors)} questions could not be routed; re-run to retry them")
    if accuracy < args.min_accuracy:
        sys.exit(f"FAIL: routing accuracy {accuracy:.2f} is below {args.min_accuracy}")


if __name__ == "__main__":
    main()
