"""Logging: readable text for development, one JSON object per line for production.

JSON logs can be searched and filtered by log tools (Render, Railway, Datadog, Loki):
    {"time": "...", "level": "INFO", "logger": "app.request", "message": "POST /chat 200",
     "request_id": "3f2a9c1e0b7d", "duration_ms": 42.1, ...}
Every log line written while handling a request carries that request's id, so one customer's
problem can be followed through all its log lines (the id is also returned as X-Request-ID).
"""

import json
import logging
from contextvars import ContextVar

request_id: ContextVar[str] = ContextVar("request_id", default="-")

# Attributes every LogRecord has; anything else was passed with extra={...}
_STANDARD = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "request_id"}


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        entry.update({k: v for k, v in record.__dict__.items() if k not in _STANDARD})
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str = "INFO", fmt: str = "text") -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
        )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for noisy in ("httpx", "httpcore", "pdfminer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
