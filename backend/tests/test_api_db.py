"""API against the real database (each test rolled back): chat log, history, feedback, tickets,
conversations, document upload / delete / re-index. Models and embeddings are fakes."""

import shutil

import pytest
from fastapi.testclient import TestClient
from langchain_core.embeddings import DeterministicFakeEmbedding
from pydantic import SecretStr
from sqlalchemy.orm import Session

from app.api import admin, chat
from app.api.security import RateLimiter, create_token
from app.config import PROJECT_ROOT, Settings, get_settings
from app.db.models import EMBED_DIM
from app.db.session import get_engine, get_session, get_session_factory
from app.main import app
from app.tools.tickets import create_ticket
from tests.test_api import SESSION, FakeAgent, parse_sse

pytestmark = pytest.mark.integration
DOCS = PROJECT_ROOT / "sample_data" / "docs"


@pytest.fixture
def db():
    """One connection in a transaction that is rolled back; every request gets its own session
    on it, like real requests get their own."""
    with get_engine().connect() as conn:
        trans = conn.begin()

        def new_session():
            return Session(bind=conn, join_transaction_mode="create_savepoint",
                           expire_on_commit=False)  # fmt: skip

        def per_request():
            s = new_session()
            try:
                yield s
            finally:
                s.close()

        app.dependency_overrides[get_session] = per_request
        app.dependency_overrides[get_session_factory] = lambda: new_session
        app.dependency_overrides[chat.get_chat_limiter] = lambda: RateLimiter(1000)
        try:
            yield new_session
        finally:
            app.dependency_overrides.clear()
            app.state.agent = None
            trans.rollback()


@pytest.fixture
def scores(monkeypatch):
    sent = []
    monkeypatch.setattr(chat, "record_feedback", lambda *a: sent.append(a))
    return sent


@pytest.fixture
def kb(tmp_path, monkeypatch):
    """Admin settings, a temporary docs folder and a fake embedder."""
    settings = Settings(_env_file=None, docs_dir="docs", uploads_dir="docs/uploads",
                        jwt_secret=SecretStr("t" * 32), max_upload_mb=1)  # fmt: skip
    (tmp_path / "docs").mkdir()
    monkeypatch.setattr(admin, "SOURCE_ROOT", tmp_path)
    monkeypatch.setattr(admin, "get_embedder", lambda s: DeterministicFakeEmbedding(size=EMBED_DIM))
    monkeypatch.setattr(admin, "embed_model_id", lambda s: "fake:test")
    app.dependency_overrides[get_settings] = lambda: settings
    return tmp_path


def auth() -> dict:
    s = app.dependency_overrides[get_settings]()
    return {"Authorization": f"Bearer {create_token(s)}"}


def say(c: TestClient, message: str, session_id=SESSION, answer="Hi [1].") -> dict:
    from tests.test_api import turn

    app.state.agent = FakeAgent(tokens=(answer,), result=turn(answer, question=message))
    events = parse_sse(c.post("/chat", json={"message": message, "session_id": session_id}).text)
    assert events[-1][0] == "done", events
    return events[-1][1]


# ---------- chat log, history, feedback ----------


def test_turns_are_logged_and_history_redraws_the_chat(db, scores):
    c = TestClient(app)
    first, second = say(c, "hello"), say(c, "returns?", answer="30 days [1].")
    history = c.get(f"/chat/{SESSION}/history").json()
    assert [(h["question"], h["answer"]) for h in history] == [
        ("hello", "Hi [1]."), ("returns?", "30 days [1].")]  # fmt: skip
    assert [h["message_id"] for h in history] == [first["message_id"], second["message_id"]]
    assert c.get(f"/chat/{'b' * 32}/history").json() == [], "other sessions see nothing"
    assert c.get("/chat/not-a-session/history").status_code == 422


def test_feedback_is_saved_changed_and_sent_to_langfuse(db, scores):
    c = TestClient(app)
    done = say(c, "returns?")
    body = {"session_id": SESSION, "message_id": done["message_id"], "rating": 1}
    assert c.post("/feedback", json=body).status_code == 204
    assert c.post("/feedback", json=body | {"rating": -1, "comment": "wrong fee"}
                  ).status_code == 204  # fmt: skip

    assert c.get(f"/chat/{SESSION}/history").json()[0]["rating"] == -1, "changed, not added"
    assert scores == [(done["message_id"], 1, None), (done["message_id"], -1, "wrong fee")]


def test_feedback_only_from_the_conversations_own_visitor(db, scores):
    c = TestClient(app)
    done = say(c, "returns?")
    other = {"session_id": "b" * 32, "message_id": done["message_id"], "rating": -1}
    assert c.post("/feedback", json=other).status_code == 404
    unknown = {"session_id": SESSION, "message_id": "c" * 32, "rating": 1}
    assert c.post("/feedback", json=unknown).status_code == 404
    assert c.post("/feedback", json=unknown | {"rating": 5}).status_code == 422
    assert scores == []


def test_admin_sees_conversations_and_thumbs_down(db, kb, scores):
    c = TestClient(app)
    say(c, "hello")
    bad = say(c, "restocking fee?", answer="No fee.")
    say(c, "other chat", session_id="d" * 32)
    c.post("/feedback", json={"session_id": SESSION, "message_id": bad["message_id"],
                              "rating": -1, "comment": "it's 10%"})  # fmt: skip

    convos = {x["thread_id"]: x for x in c.get("/admin/conversations", headers=auth()).json()}
    assert convos[SESSION]["turns"] == 2 and convos[SESSION]["first_question"] == "hello"
    assert convos[SESSION]["thumbs_down"] == 1 and convos["d" * 32]["thumbs_down"] == 0

    detail = c.get(f"/admin/conversations/{SESSION}", headers=auth()).json()
    assert [t["question"] for t in detail] == ["hello", "restocking fee?"]
    assert detail[1]["comment"] == "it's 10%" and "safety" in detail[1], "admins see details"
    assert c.get(f"/admin/conversations/{'e' * 32}", headers=auth()).status_code == 404

    def rated(rating: int) -> list[str]:  # this test's chats only: the database may have others
        found = c.get(f"/admin/feedback?rating={rating}", headers=auth()).json()
        return [f["question"] for f in found if f["thread_id"] in (SESSION, "d" * 32)]

    assert rated(-1) == ["restocking fee?"] and rated(1) == []


# ---------- tickets ----------


def test_ticket_inbox(db, kb):
    with db() as s, s.begin():
        open_ref = create_ticket(
            s, thread_id="t1", name="Ana", email="ana@example.com", summary="Wants a human",
            reason="customer_request", transcript=[{"role": "user", "content": "human please"}],
        )  # fmt: skip
        create_ticket(s, thread_id="t2", name=None, email="bo@example.com", summary="Locked",
                      reason="verification_locked", transcript=[])  # fmt: skip
    c = TestClient(app)
    tickets = c.get("/admin/tickets", headers=auth()).json()
    mine = [t for t in tickets if t["thread_id"] in ("t1", "t2")]
    assert [t["thread_id"] for t in mine] == ["t2", "t1"], "newest first"

    ticket_id = next(t["id"] for t in mine if t["reference"] == open_ref)
    detail = c.get(f"/admin/tickets/{ticket_id}", headers=auth()).json()
    assert detail["transcript"] == [{"role": "user", "content": "human please"}]

    patched = c.patch(f"/admin/tickets/{ticket_id}", json={"status": "closed"}, headers=auth())
    assert patched.json()["status"] == "closed"
    closed = c.get("/admin/tickets?status=closed", headers=auth()).json()
    assert ticket_id in [t["id"] for t in closed]
    assert c.patch(f"/admin/tickets/{ticket_id}", json={"status": "done"},
                   headers=auth()).status_code == 422  # fmt: skip
    assert c.get("/admin/tickets/999999", headers=auth()).status_code == 404


# ---------- documents ----------


def upload(c: TestClient, name: str, data: bytes):
    return c.post("/admin/documents", files={"file": (name, data)}, headers=auth())


def returns_page() -> bytes:
    return (DOCS / "returns-and-refunds.html").read_bytes()


def files(sources: list[str]) -> list[str]:
    """Leaves out catalog entries (an empty test database indexes the catalog on first run)."""
    return [s for s in sources if not s.startswith("catalog:")]


def listed(c: TestClient) -> dict:
    return {d["source"]: d for d in c.get("/admin/documents", headers=auth()).json()}


def test_upload_makes_a_document_searchable_and_delete_removes_it(db, kb):
    c = TestClient(app)
    response = upload(c, "Returns Policy.html", returns_page())
    assert response.status_code == 201, response.text
    source = "docs/uploads/Returns-Policy.html"
    assert files(response.json()["added"]) == [source]
    assert (kb / source).exists()

    doc = listed(c)[source]
    assert doc["chunks"] > 3 and doc["deletable"] and doc["doc_type"] == "help_center"

    again = upload(c, "Returns Policy.html", returns_page()).json()
    assert again["added"] == again["updated"] == [] and again["chunks_embedded"] == 0

    assert c.delete(f"/admin/documents/{doc['id']}", headers=auth()).status_code == 204
    assert source not in listed(c) and not (kb / source).exists()
    assert c.delete(f"/admin/documents/{doc['id']}", headers=auth()).status_code == 404


def test_catalog_entries_cannot_be_deleted(db, kb):
    c = TestClient(app)
    c.post("/admin/reindex", headers=auth())  # makes sure catalog entries exist
    catalog = next(d for d in listed(c).values() if d["source"].startswith("catalog:"))
    assert not catalog["deletable"]
    assert c.delete(f"/admin/documents/{catalog['id']}", headers=auth()).status_code == 400


@pytest.mark.parametrize(
    ("name", "data", "code"),
    [
        ("broken.pdf", b"not really a pdf", 422),
        ("empty.html", b"<html><body></body></html>", 422),
        ("notes.txt", b"hello", 415),
        ("huge.html", b"x" * (1024 * 1024 + 1), 413),
    ],
)
def test_bad_uploads_change_nothing(db, kb, name, data, code):
    c = TestClient(app)
    before = listed(c)
    assert upload(c, name, data).status_code == code
    assert listed(c) == before
    assert not (kb / "docs" / "uploads").exists() or not any((kb / "docs/uploads").iterdir())


def test_failed_indexing_keeps_the_folder_as_it_was(db, kb, monkeypatch):
    class Down:
        def embed_documents(self, texts):
            raise ConnectionError("cohere down")

    monkeypatch.setattr(admin, "get_embedder", lambda s: Down())
    c = TestClient(app)
    response = upload(c, "new.html", returns_page())
    assert response.status_code == 502 and "cohere" not in response.text
    assert not (kb / "docs/uploads/new.html").exists()


def test_reindex_picks_up_added_and_removed_files(db, kb):
    c = TestClient(app)
    shutil.copy(DOCS / "shipping-policy.html", kb / "docs" / "shipping.html")
    result = c.post("/admin/reindex", headers=auth()).json()
    assert files(result["added"]) == ["docs/shipping.html"]

    (kb / "docs" / "shipping.html").unlink()
    assert c.post("/admin/reindex", headers=auth()).json()["deleted"] == ["docs/shipping.html"]


def test_one_ingest_at_a_time(db, kb):
    admin.ingest_lock.acquire()
    try:
        assert TestClient(app).post("/admin/reindex", headers=auth()).status_code == 409
    finally:
        admin.ingest_lock.release()
