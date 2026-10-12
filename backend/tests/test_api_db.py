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
from app.db.models import EMBED_DIM, Product, Ticket
from app.db.session import get_engine, get_session, get_session_factory
from app.graph.prompts import TICKET_EXISTS
from app.main import app
from app.tools.tickets import create_ticket
from tests.test_agent import Spy, make_agent, route
from tests.test_api import SESSION, FakeAgent, parse_sse, turn

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


def say(c: TestClient, message: str, session_id=SESSION, answer="Hi [1].", **fields) -> dict:
    app.state.agent = FakeAgent(tokens=(answer,), result=turn(answer, question=message, **fields))
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


# ---------- product cards ----------


def test_cited_products_come_with_live_catalog_data(db):
    with db() as s:
        product = s.query(Product).order_by(Product.sku).first()
    citations = [
        {"n": 1, "source": "sample_data/docs/returns-and-refunds.html", "title": "Returns"},
        {"n": 2, "source": f"catalog:{product.sku}", "title": product.name},
        {"n": 3, "source": "catalog:NO-SUCH-SKU", "title": "Gone"},
    ]
    done = say(TestClient(app), "which one?", citations=citations)
    assert [p["sku"] for p in done["products"]] == [product.sku], "only real catalog products"
    card = done["products"][0]
    assert card["price_usd"] == float(product.price_usd) and card["stock"] and card["rating"]


def test_cards_for_products_a_cited_guide_covers_and_the_answer_names(db):
    with db() as s:
        first, second = s.query(Product).order_by(Product.sku).limit(2).all()
    guide = {"n": 1, "source": "sample_data/docs/guide.docx", "title": "Guide",
             "products": [first.sku, second.sku]}  # fmt: skip
    answer = f"For running, pick the {first.name} [1]."
    done = say(TestClient(app), "running?", answer=answer, citations=[guide])
    assert [p["sku"] for p in done["products"]] == [first.sku], "named in the answer: card"


# ---------- contact form (handoff) ----------


def form(c: TestClient, **fields):
    body = {"session_id": SESSION, "email": "Ana@Example.com", "name": "Ana Lopez",
            "message": "My laptop arrived cracked"} | fields  # fmt: skip
    return c.post("/handoff", json=body)


def graph_agent(*routes):
    agent, _ = make_agent(Spy([route(r) for r in routes]), answers=["Fee is 10% [1]."])
    app.state.agent = agent
    return agent


def test_contact_form_creates_a_ticket_with_the_chat_so_far(db):
    c = TestClient(app)
    say(c, "returns?", answer="30 days [1].")
    agent = graph_agent()
    response = form(c)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created"] and body["ticket_ref"] in body["message"]
    assert "Thanks, Ana!" in body["message"] and "ana@example.com" in body["message"]

    with db() as s:
        ticket = s.get(Ticket, int(body["ticket_ref"][2:]))
        assert ticket.email == "ana@example.com" and ticket.summary == "My laptop arrived cracked"
        assert ticket.transcript == [{"role": "user", "content": "returns?"},
                                     {"role": "assistant", "content": "30 days [1]."}]  # fmt: skip
        assert ticket.reason == "customer_request"
    assert agent.state(SESSION)["ticket_ref"] == body["ticket_ref"], "the bot knows"
    history = c.get(f"/chat/{SESSION}/history").json()
    assert history[-1]["answer"] == body["message"], "a page reload still shows it"


def test_second_form_and_later_chat_reuse_the_ticket(db):
    c = TestClient(app)
    agent = graph_agent("handoff")
    ref = form(c).json()["ticket_ref"]
    again = form(c).json()
    assert again == {"ticket_ref": ref, "message": TICKET_EXISTS.format(ref=ref),
                     "created": False}  # fmt: skip
    # Then asking the bot for a human: it already knows about the ticket
    assert agent.ask(SESSION, "can I talk to a human?").answer == TICKET_EXISTS.format(ref=ref)


def test_ticket_reason_comes_from_the_conversation(db):
    agent = graph_agent("product_info")
    agent.graph.update_state({"configurable": {"thread_id": SESSION}},
                             {"handoff_reason": "no_answer"}, as_node="handoff")  # fmt: skip
    ref = form(TestClient(app)).json()["ticket_ref"]
    with db() as s:
        assert s.get(Ticket, int(ref[2:])).reason == "no_answer"


def test_card_numbers_are_removed_from_the_ticket(db):
    graph_agent()
    ref = form(TestClient(app), message="charged twice on 4111 1111 1111 1111").json()["ticket_ref"]
    with db() as s:
        assert "4111" not in s.get(Ticket, int(ref[2:])).summary


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
