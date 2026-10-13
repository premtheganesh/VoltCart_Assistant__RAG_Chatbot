from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.db.session import get_session
from app.main import app


def _client_with_session(session) -> TestClient:
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_health_ok_when_db_reachable():
    session = MagicMock()
    session.execute.return_value.scalar.return_value = "0.8.0"

    response = _client_with_session(session).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok", "db": "ok", "pgvector": "0.8.0", "agent": "unavailable",
    }  # fmt: skip


def test_health_503_when_db_unreachable():
    session = MagicMock()
    session.execute.side_effect = OperationalError("SELECT 1", {}, Exception("refused"))

    response = _client_with_session(session).get("/health")

    assert response.status_code == 503
    assert response.json()["db"] == "unreachable"


def test_database_url_uses_psycopg_driver_and_port():
    settings = Settings(_env_file=None, postgres_port=5433, postgres_password="pw")

    assert settings.database_url == "postgresql+psycopg://voltcart:pw@localhost:5433/voltcart"


@pytest.mark.integration
def test_health_against_real_database():
    """Requires `make db-up`. Run with: make test-all"""
    response = TestClient(app).get("/health")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["db"] == "ok"
    assert body["pgvector"] not in (None, "missing")
