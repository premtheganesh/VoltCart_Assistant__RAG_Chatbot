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


class DailyLimitReached(RuntimeError):
    """A provider's daily quota is used up: retrying is pointless until it resets."""


def is_daily_limit(exc: BaseException) -> bool:
    # Groq: "Rate limit reached ... on tokens per day (TPD)" / "requests per day (RPD)"
    text = str(exc)
    return "per day" in text or "(TPD)" in text or "(RPD)" in text


def stop_if_daily_limit(exc: BaseException) -> None:
    if is_daily_limit(exc):
        model = text.split("`")[1] if (text := str(exc)).count("`") >= 2 else "a model"
        raise DailyLimitReached(
            f"Daily quota used up for {model}. Finished results are cached: run this again "
            "after the quota resets (Groq resets within 24 hours)."
        ) from exc
