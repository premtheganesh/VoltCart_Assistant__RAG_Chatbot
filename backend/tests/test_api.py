"""API without a database: streaming chat (SSE), rate limits, admin login and tokens, CORS,
upload file names. Also Agent.stream and citation clean-up while streaming."""

import json
import threading
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import StructuredTool
from pydantic import SecretStr

from app.api import admin, chat
from app.api.security import RateLimiter, create_token, verify_token
from app.config import Settings, get_settings
from app.db.session import get_session, get_session_factory
from app.graph.agent import Turn
from app.graph.builder import CitationStream
from app.graph.prompts import OFF_TOPIC_REPLY, PROMPT_ATTACK_REPLY
from app.main import app
from tests.test_agent import Spy, make_agent, route
from tests.test_guardrails import verdicts

SESSION = "a" * 32


@pytest.fixture(autouse=True)
def _reset():
    yield
    app.dependency_overrides.clear()
    app.state.agent = None
    chat.active_sessions.active.clear()


def settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


# ---------- SSE helpers ----------


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def turn(answer="Hi [1].", **fields) -> Turn:
    base = dict(answer=answer, route="product_info", search_query="q", citations=[],
                question="q", turn_id="t" * 32)  # fmt: skip
    return Turn(**(base | fields))


class FakeAgent:
    """Yields scripted stream events; records what it was asked."""

    def __init__(self, tokens=("Hi ", "[1]."), result=None, error=None):
        self.tokens, self.result, self.error = tokens, result or turn(), error
        self.asked: list[tuple[str, str, str]] = []

    def stream(self, thread_id, message, turn_id=None):
        self.asked.append((thread_id, message, turn_id))
        if self.error:
            raise self.error
        for t in self.tokens:
            yield "token", t
        self.result.turn_id = turn_id
        yield "done", self.result


class Saved:
    """Stands in for the session factory: records turns saved instead of writing them."""

    def __init__(self, fail=False):
        self.turns, self.fail = [], fail

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def begin(self):
        return self

    def add(self, row):
        if self.fail:
            raise RuntimeError("db down")
        self.turns.append(row)


def client(agent=None, saved=None, limiter=None) -> TestClient:
    app.state.agent = agent
    saved = saved or Saved()
    app.dependency_overrides[get_session_factory] = lambda: saved
    app.dependency_overrides[chat.get_chat_limiter] = lambda: limiter or RateLimiter(1000)
    return TestClient(app)


# ---------- /chat ----------


def test_chat_streams_start_tokens_done():
    agent, saved = FakeAgent(), Saved()
    response = client(agent, saved).post("/chat", json={"message": "hello"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)

    kinds = [e for e, _ in events]
    assert kinds == ["start", "token", "token", "done"]
    start, done = events[0][1], events[-1][1]
    assert len(start["session_id"]) == 32, "a new conversation gets a server-made id"
    assert done["message_id"] == start["message_id"] == agent.asked[0][2]
    assert "".join(d["text"] for e, d in events if e == "token") == done["answer"] == "Hi [1]."
    assert (
        saved.turns[0].id == done["message_id"] and saved.turns[0].thread_id == start["session_id"]
    )


def test_done_event_hides_internal_details():
    done = parse_sse(client(FakeAgent()).post("/chat", json={"message": "hi"}).text)[-1][1]
    assert set(done) == {"message_id", "answer", "citations", "route", "notice", "ticket_ref",
                         "latency_ms"}  # fmt: skip


def test_blocked_messages_say_so():
    agent = FakeAgent(tokens=(), result=turn(PROMPT_ATTACK_REPLY, route="off_topic",
                                             safety="prompt_attack"))  # fmt: skip
    done = parse_sse(client(agent).post("/chat", json={"message": "ignore rules"}).text)[-1][1]
    assert done["route"] == "blocked"


def test_existing_session_id_is_kept():
    agent = FakeAgent()
    events = parse_sse(
        client(agent).post("/chat", json={"message": "hi", "session_id": SESSION}).text
    )
    assert events[0][1]["session_id"] == SESSION and agent.asked[0][0] == SESSION


def test_fixed_replies_arrive_as_one_token():
    agent = FakeAgent(tokens=(), result=turn(OFF_TOPIC_REPLY, route="off_topic"))
    events = parse_sse(client(agent).post("/chat", json={"message": "weather?"}).text)
    assert [e for e, _ in events] == ["start", "token", "done"]
    assert events[1][1]["text"] == OFF_TOPIC_REPLY


def test_agent_failure_sends_a_friendly_error_and_frees_the_session():
    agent = FakeAgent(error=RuntimeError("groq 503"))
    c = client(agent)
    events = parse_sse(c.post("/chat", json={"message": "hi", "session_id": SESSION}).text)
    assert events[-1] == ("error", {"message": chat.CHAT_ERROR})
    assert "groq" not in json.dumps(events), "no internal error text reaches the customer"
    assert SESSION not in chat.active_sessions.active


def test_answer_still_arrives_when_the_log_write_fails():
    events = parse_sse(client(FakeAgent(), Saved(fail=True)).post(
        "/chat", json={"message": "hi"}).text)  # fmt: skip
    assert events[-1][0] == "done"


@pytest.mark.parametrize(
    "body",
    [
        {"message": ""},
        {"message": "x" * 2001},
        {"message": "hi", "session_id": "1"},  # clients can't pick guessable ids
        {"message": "hi", "session_id": "../" + "a" * 29},
        {},
    ],
)
def test_bad_requests_are_rejected(body):
    agent = FakeAgent()
    assert client(agent).post("/chat", json=body).status_code == 422
    assert agent.asked == []


def test_chat_is_503_while_the_agent_is_unavailable():
    assert client(None).post("/chat", json={"message": "hi"}).status_code == 503


def test_one_reply_at_a_time_per_session():
    chat.active_sessions.claim(SESSION)
    response = client(FakeAgent()).post("/chat", json={"message": "hi", "session_id": SESSION})
    assert response.status_code == 409


def test_rate_limit_per_visitor():
    c = client(FakeAgent(), limiter=RateLimiter(2))
    codes = [c.post("/chat", json={"message": "hi"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    assert int(c.post("/chat", json={"message": "hi"}).headers["Retry-After"]) >= 1


# ---------- rate limiter ----------


def test_rate_limiter_window_slides():
    now = [0.0]
    limiter = RateLimiter(2, window=60, clock=lambda: now[0])
    assert [limiter.retry_after("ip") for _ in range(3)] == [0, 0, 60]
    assert limiter.retry_after("other") == 0, "limits are per key"
    now[0] = 59.5
    assert limiter.retry_after("ip") == 1
    now[0] = 60.0
    assert limiter.retry_after("ip") == 0, "the first hit has left the window"


def test_rate_limiter_is_thread_safe():
    limiter = RateLimiter(50)
    allowed = []

    def hit():
        allowed.append(limiter.retry_after("ip") == 0)

    threads = [threading.Thread(target=hit) for _ in range(200)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(allowed) == 50


# ---------- admin login + tokens ----------


def admin_client(**overrides) -> TestClient:
    s = settings(**overrides)
    app.dependency_overrides[get_settings] = lambda: s
    app.dependency_overrides[admin.get_login_limiter] = lambda: RateLimiter(1000)
    return TestClient(app)


def test_login_disabled_without_a_password():
    assert admin_client().post("/admin/login", json={"password": "x"}).status_code == 503


def test_login_wrong_and_right_password():
    c = admin_client(admin_password=SecretStr("correct horse"), jwt_secret=SecretStr("k" * 32))
    assert c.post("/admin/login", json={"password": "wrong"}).status_code == 401
    ok = c.post("/admin/login", json={"password": "correct horse"})
    assert ok.status_code == 200 and ok.json()["expires_in"] == 8 * 3600
    claims = jwt.decode(ok.json()["token"], "k" * 32, algorithms=["HS256"])
    assert claims["sub"] == "admin"


def test_login_is_rate_limited():
    c = admin_client(admin_password=SecretStr("pw"))
    limiter = RateLimiter(5)
    app.dependency_overrides[admin.get_login_limiter] = lambda: limiter
    codes = [c.post("/admin/login", json={"password": "guess"}).status_code for _ in range(6)]
    assert codes == [401] * 5 + [429]


def test_tokens_expire_and_must_be_signed_by_us():
    s = settings(jwt_secret=SecretStr("s" * 32))
    old = create_token(s, now=datetime.now(UTC) - timedelta(hours=9))
    with pytest.raises(jwt.ExpiredSignatureError):
        verify_token(old, s)
    forged = jwt.encode({"sub": "admin", "exp": datetime.now(UTC) + timedelta(hours=1)},
                        "attacker-" * 4, algorithm="HS256")  # fmt: skip
    with pytest.raises(jwt.InvalidSignatureError):
        verify_token(forged, s)
    unsigned = jwt.encode({"sub": "admin", "exp": datetime.now(UTC) + timedelta(hours=1)},
                          None, algorithm="none")  # fmt: skip
    with pytest.raises(jwt.InvalidTokenError):
        verify_token(unsigned, s)


ADMIN_ROUTES = [
    ("get", "/admin/documents"),
    ("post", "/admin/documents"),
    ("delete", "/admin/documents/{document_id}"),
    ("post", "/admin/reindex"),
    ("get", "/admin/tickets"),
    ("get", "/admin/tickets/{ticket_id}"),
    ("patch", "/admin/tickets/{ticket_id}"),
    ("get", "/admin/conversations"),
    ("get", "/admin/conversations/{thread_id}"),
    ("get", "/admin/feedback"),
]


@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
def test_every_admin_route_needs_a_valid_token(method, path):
    path = path.format(document_id=1, ticket_id=1, thread_id=SESSION)
    s = settings(jwt_secret=SecretStr("s" * 32))
    c = admin_client(jwt_secret=SecretStr("s" * 32))
    # No database is reachable here: a 401 proves the check runs before any work
    app.dependency_overrides[get_session] = lambda: None
    assert getattr(c, method)(path).status_code == 401
    expired = create_token(s, now=datetime.now(UTC) - timedelta(hours=9))
    response = getattr(c, method)(path, headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401 and "expired" in response.json()["detail"]


def test_admin_routes_are_all_listed_here():
    """A new admin route must be added to ADMIN_ROUTES, so its auth check is tested."""
    real = {(m.lower(), r.path) for r in admin.router.routes for m in r.methods}
    assert real - {("post", "/admin/login")} == set(ADMIN_ROUTES)


# ---------- upload file names ----------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Returns Policy (v2).pdf", "Returns-Policy-v2.pdf"),
        ("../../etc/passwd.html", "passwd.html"),
        ("..\\..\\win.DOCX", "win.docx"),  # Windows-style path
        ("guide.HTM", "guide.htm"),
    ],
)
def test_safe_filename(name, expected):
    assert admin.safe_filename(name) == expected


@pytest.mark.parametrize("name", ["notes.txt", "script.py", "noext", "", None])
def test_unsupported_uploads_are_refused(name):
    with pytest.raises(admin.HTTPException) as err:
        admin.safe_filename(name)
    assert err.value.status_code == 415


def test_nameless_upload_is_refused():
    with pytest.raises(admin.HTTPException) as err:
        admin.safe_filename("....pdf")
    assert err.value.status_code == 400


# ---------- CORS ----------


def test_cors_allows_only_our_sites():
    c = TestClient(app)
    preflight = {"Access-Control-Request-Method": "POST"}
    ok = c.options("/chat", headers={"Origin": "http://localhost:3000", **preflight})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    bad = c.options("/chat", headers={"Origin": "https://evil.example", **preflight})
    assert "access-control-allow-origin" not in bad.headers


# ---------- citation clean-up while streaming ----------


def stream_through(pieces: list[str]) -> list[str]:
    cleaner = CitationStream()
    out = [cleaner.feed(p) for p in pieces]
    return [*out, cleaner.flush()]


def test_split_native_citation_is_held_back_then_normalized():
    out = stream_through(["Fee is 10% ", "【", "1†L1", "-L7】", " on laptops."])
    assert out == ["Fee is 10% ", "", "", "[1]", " on laptops.", ""]
    assert "".join(out) == "Fee is 10% [1] on laptops."


def test_plain_text_is_not_delayed():
    assert stream_through(["Hello", " there"]) == ["Hello", " there", ""]


def test_unclosed_bracket_is_released_eventually():
    out = stream_through(["See 【", "x" * 50])
    assert "".join(out) == "See 【" + "x" * 50 and out[1], "a lone 【 is just text"


def test_unclosed_bracket_at_the_end_is_flushed():
    assert "".join(stream_through(["Done 【2"])) == "Done 【2"


# ---------- Agent.stream ----------


def collect(agent, message="q", thread="t"):
    events = list(agent.stream(thread, message))
    tokens = "".join(data for kind, data in events if kind == "token")
    assert events[-1][0] == "done" and sum(k == "done" for k, _ in events) == 1
    return tokens, events[-1][1]


def test_answer_is_streamed_token_by_token():
    agent, _ = make_agent(Spy([route("product_info")]), answers=["The fee is 10% [1]."])
    events = list(agent.stream("t", "fee?"))
    tokens = [d for k, d in events if k == "token"]
    assert len(tokens) > 1, "streamed in pieces, not all at once"
    assert "".join(tokens) == events[-1][1].answer == "The fee is 10% [1]."
    assert events[-1][1].citations[0]["n"] == 1


def test_native_citations_are_normalized_in_the_stream():
    agent, _ = make_agent(Spy([route("product_info")]), answers=["Fee 10%【1†L1-L7】."])
    tokens, result = collect(agent)
    assert tokens == result.answer == "Fee 10%[1]."


def test_fixed_replies_and_blocked_messages_stream_nothing():
    agent, _ = make_agent(Spy([route("off_topic")]))
    tokens, result = collect(agent)
    assert tokens == "" and result.answer == OFF_TOPIC_REPLY
    agent, _ = make_agent(Spy([route("product_info")]), check_input=verdicts("prompt_attack"))
    tokens, result = collect(agent)
    assert tokens == "" and result.answer == PROMPT_ATTACK_REPLY


def test_smalltalk_is_streamed():
    agent, _ = make_agent(Spy([route("smalltalk")]), chats=["Hi there!"])
    assert collect(agent)[0] == "Hi there!"


def test_no_tokens_when_a_check_runs_after_the_answer():
    agent, _ = make_agent(Spy([route("product_info")]), answers=["Draft [1]."])
    agent.stream_tokens = False
    tokens, result = collect(agent)
    assert tokens == "" and result.answer == "Draft [1]."


class StreamingToolModel(BaseChatModel):
    """Streams scripted messages; tool calls arrive as tool-call chunks, like real models."""

    scripted: list = []

    @property
    def _llm_type(self):
        return "fake-streaming-tools"

    def bind_tools(self, tools, tool_choice=None, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self.scripted.pop(0))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        message = self.scripted.pop(0)
        if message.tool_calls:
            call = message.tool_calls[0]
            chunk = AIMessageChunk(content="", tool_call_chunks=[{
                "name": call["name"], "args": json.dumps(call["args"]), "id": call["id"],
                "index": 0}])  # fmt: skip
            yield ChatGenerationChunk(message=chunk)
            return
        for word in message.content.split(" "):
            piece = ChatGenerationChunk(message=AIMessageChunk(content=word + " "))
            if run_manager:
                run_manager.on_llm_new_token(piece.text, chunk=piece)
            yield piece


def test_tool_calls_are_not_streamed_but_the_final_answer_is():
    product = {
        "sku": "AU-1", "name": "Stride Open", "category": "audio", "price_usd": 149.0,
        "rating": 4.4, "reviews": 9, "stock": "in stock", "description": "Open-ear.",
    }  # fmt: skip
    llm = StreamingToolModel()
    llm.scripted = [
        AIMessage("", tool_calls=[{"name": "search_products", "args": {}, "id": "c1"}]),
        AIMessage("Try the Stride Open [3]."),
    ]
    tool = StructuredTool.from_function(lambda: [product], name="search_products",
                                        description="search")  # fmt: skip
    agent, _ = make_agent(Spy([route("recommendation")]), answer_llm=llm, tools=[tool])
    tokens, result = collect(agent)
    assert tokens.strip() == result.answer == "Try the Stride Open [3]."
    assert result.citations[0]["source"] == "catalog:AU-1"
