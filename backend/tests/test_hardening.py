"""Phase 12: client IPs behind proxies, request ids, JSON logs."""

import json
import logging
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api.security import client_ip
from app.logging_setup import JsonFormatter, RequestIdFilter, request_id
from app.main import app


def req(peer: str, forwarded: str | None = None):
    headers = {"x-forwarded-for": forwarded} if forwarded else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


PROXY = {"10.0.0.2"}


def test_direct_connections_ignore_forwarded_headers():
    """Anyone can send X-Forwarded-For: believing it would let a client dodge rate limits."""
    assert client_ip(req("203.0.113.9", "1.2.3.4"), PROXY) == "203.0.113.9"


def test_behind_a_trusted_proxy_the_visitor_is_the_last_untrusted_hop():
    assert client_ip(req("10.0.0.2", "198.51.100.7"), PROXY) == "198.51.100.7"
    # The client prepended a fake address; our proxy appended the real one
    assert client_ip(req("10.0.0.2", "1.1.1.1, 198.51.100.7"), PROXY) == "198.51.100.7"
    # Two of our proxies in a row
    assert client_ip(req("10.0.0.2", "198.51.100.7, 10.0.0.3"), PROXY | {"10.0.0.3"}) == (
        "198.51.100.7"
    )
    assert client_ip(req("10.0.0.2"), PROXY) == "10.0.0.2", "no header: the proxy itself"


def test_every_response_carries_a_request_id():
    c = TestClient(app)
    generated = c.get("/admin/tickets").headers["X-Request-ID"]
    assert len(generated) == 12
    assert (
        c.get("/admin/tickets", headers={"X-Request-ID": "lb-abc.123"}).headers["X-Request-ID"]
        == "lb-abc.123"
    ), "a proxy's id is kept, so logs line up across systems"
    junk = c.get("/admin/tickets", headers={"X-Request-ID": "x" * 80 + "\n"}).headers
    assert junk["X-Request-ID"] != "x" * 80, "unsafe ids are replaced, not logged"


def test_json_log_lines_carry_the_request_id_and_extra_fields():
    record = logging.makeLogRecord(
        {"name": "app.request", "levelname": "INFO", "msg": "POST /chat 200",
         "duration_ms": 41.5, "status": 200}
    )  # fmt: skip
    token = request_id.set("abc123")
    try:
        RequestIdFilter().filter(record)
    finally:
        request_id.reset(token)
    line = json.loads(JsonFormatter().format(record))
    assert line["message"] == "POST /chat 200" and line["request_id"] == "abc123"
    assert line["duration_ms"] == 41.5 and line["status"] == 200 and line["level"] == "INFO"


def test_the_access_log_line_carries_the_same_id_as_the_response(caplog):
    caplog.set_level(logging.INFO, logger="app.request")
    response = TestClient(app).get("/admin/tickets", headers={"X-Request-ID": "trace-42"})
    lines = [r for r in caplog.records if r.name == "app.request"]
    assert lines and lines[-1].request_id == "trace-42" == response.headers["X-Request-ID"]
    assert lines[-1].status == 401 and lines[-1].duration_ms >= 0
