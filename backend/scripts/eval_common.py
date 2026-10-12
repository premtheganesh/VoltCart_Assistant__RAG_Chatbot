"""Shared by the eval scripts: each writes its headline numbers to evals/reports/<name>.json,
which `make eval` (scripts/eval_all.py) compares against evals/thresholds.toml."""

import json
from datetime import UTC, datetime

from app.config import PROJECT_ROOT

REPORTS = PROJECT_ROOT / "evals" / "reports"


def write_metrics(name: str, metrics: dict) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    payload = {"eval": name, "run_at": datetime.now(UTC).isoformat(timespec="seconds"), **metrics}
    (REPORTS / f"{name}.json").write_text(json.dumps(payload, indent=2) + "\n")


def read_metrics(name: str) -> dict | None:
    path = REPORTS / f"{name}.json"
    return json.loads(path.read_text()) if path.exists() else None
