"""Compare the latest eval results with the quality gates in evals/thresholds.toml.

    make eval            # runs every eval, then this summary
    make eval-summary    # just this summary, from the last results (no API calls)

Writes evals/reports/summary.md and exits with an error if any gate fails, so CI can use it.
"""

import sys
import tomllib
from datetime import UTC, datetime

from app.config import PROJECT_ROOT
from scripts.eval_common import REPORTS, read_metrics

THRESHOLDS = PROJECT_ROOT / "evals" / "thresholds.toml"


def check(thresholds: dict, results: dict[str, dict | None]) -> list[dict]:
    rows = []
    for eval_name, metrics in thresholds.items():
        for metric, rule in metrics.items():
            data = results.get(eval_name)
            value = data.get(metric) if data else None
            if value is None:
                ok = None  # not run yet
            elif "min" in rule:
                ok = value >= rule["min"]
            else:
                ok = value <= rule["max"]
            target = f"≥ {rule['min']}" if "min" in rule else f"≤ {rule['max']}"
            rows.append({"label": rule["label"], "eval": eval_name, "value": value,
                         "target": target, "ok": ok})  # fmt: skip
    return rows


def caveats(results: dict[str, dict | None]) -> list[str]:
    """Things that make a number less trustworthy than it looks."""
    notes = []
    if (r := results.get("routing")) and r.get("scored", 0) < r.get("total", 0):
        notes.append(f"Routing scored {r['scored']} of {r['total']} questions "
                     f"(the rest hit rate limits: re-run make eval-routing).")  # fmt: skip
    if (g := results.get("guardrails")) and g.get("level") != "full":
        notes.append(
            "Guardrails were measured at input level only: run "
            'make eval-guardrails args="--level full" for the end-to-end number.'
        )
    if (a := results.get("answers")) and a.get("sample") != "all":
        notes.append(
            f"Answers were graded on {a['questions']} of the 122 golden questions "
            f'({a["sample"]}). Run make eval-answers args="--all" for the full set.'
        )
    if a and a.get("not_scored"):
        notes.append(f"Answers not scored (rate limits): {a['not_scored']}.")
    return notes


def main() -> None:
    thresholds = tomllib.loads(THRESHOLDS.read_text())
    results = {name: read_metrics(name) for name in thresholds}
    rows = check(thresholds, results)
    lines = [
        "# Eval summary", "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC from the latest results in "
        "`evals/reports/`. Gates: `evals/thresholds.toml`.", "",
        "| Metric | Result | Target | Status | Measured |", "| --- | --- | --- | --- | --- |",
    ]  # fmt: skip
    for r in rows:
        status = {True: "pass", False: "**FAIL**", None: "not run"}[r["ok"]]
        run_at = (results[r["eval"]] or {}).get("run_at", "")[:16].replace("T", " ")
        lines.append(f"| {r['label']} | {r['value'] if r['value'] is not None else '—'} | "
                     f"{r['target']} | {status} | {run_at} |")  # fmt: skip
    if notes := caveats(results):
        lines += ["", "## Caveats", "", *(f"- {n}" for n in notes)]
    (REPORTS / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))

    failed = [r["label"] for r in rows if r["ok"] is False]
    missing = [r["label"] for r in rows if r["ok"] is None]
    if failed or missing:
        sys.exit(f"\nGates not met: {failed + missing}")
    print("\nAll quality gates pass.")


if __name__ == "__main__":
    main()
