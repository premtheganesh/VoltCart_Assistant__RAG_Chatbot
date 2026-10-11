"""Agent graph: routing, memory, grounding and citations, with fake models (no API calls)."""

from datetime import date

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from app.config import Settings
from app.graph.agent import Agent, fallback_analysis, make_analyzer
from app.graph.builder import build_graph, extract_citations, normalize_citations
from app.graph.prompts import NO_ANSWER_REPLY, OFF_TOPIC_REPLY
from app.graph.state import Analysis
from app.llm.chat import get_chat_model
from app.retrieval.retriever import RetrievalResult, RetrievedChunk


def chunk(n: int, heading: str, content: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=n, source=f"sample_data/docs/doc{n}.html", title="Doc", doc_type="help_center",
        url=f"https://voltcart.example/help/doc{n}", heading=heading, content=content, page=None,
        products=[], score=0.9,
    )  # fmt: skip


SOURCES = [
    chunk(1, "Returns > Is there a restocking fee?", "10% on opened laptops and phones."),
    chunk(2, "Returns > How long?", "30 days from delivery."),
]


class Spy:
    """Records what each fake dependency was called with."""

    def __init__(self, routes: list[Analysis], gate: bool = True):
        self.routes, self.gate = iter(routes), gate
        self.analyzed: list[list] = []
        self.searched: list[str] = []

    def analyze(self, messages):
        self.analyzed.append(messages)
        return next(self.routes)

    def retrieve(self, query, doc_types=None):
        self.searched.append(query)
        return RetrievalResult(
            query=query, mode="hybrid_rerank", chunks=SOURCES,
            top_score=0.9 if self.gate else 0.05, passed_gate=self.gate,
        )  # fmt: skip


class RecordingChat(FakeListChatModel):
    """Fake chat model that also keeps every prompt it was sent."""

    seen: list = Field(default_factory=list)

    def _call(self, messages, *args, **kwargs):
        self.seen.append(messages)
        return super()._call(messages, *args, **kwargs)


def make_agent(spy: Spy, answers=("Answer [1].",), chats=("Hello!",), **deps):
    answer_llm = deps.pop("answer_llm", None) or RecordingChat(responses=list(answers))
    graph = build_graph(
        analyze=spy.analyze,
        retrieve=spy.retrieve,
        answer_llm=answer_llm,
        chat_llm=FakeListChatModel(responses=list(chats)),
        checkpointer=InMemorySaver(),
        today=lambda: date(2026, 10, 10),
        **deps,
    )
    return Agent(graph, Settings(_env_file=None)), answer_llm  # no tracer: tests stay offline


def route(r: str, q: str = "q") -> Analysis:
    return Analysis(route=r, search_query=q)


# ---------- routing ----------


def test_product_question_retrieves_and_answers_with_citations():
    spy = Spy([route("product_info", "restocking fee opened laptop")])
    agent, _ = make_agent(spy, answers=["A 10% fee applies [1]. You have 30 days [2]."])

    turn = agent.ask("t", "Is there a restocking fee?")

    assert spy.searched == ["restocking fee opened laptop"], "searches the rewritten query"
    assert turn.route == "product_info" and turn.passed_gate is True
    assert turn.answer == "A 10% fee applies [1]. You have 30 days [2]."
    assert [c["n"] for c in turn.citations] == [1, 2]
    assert turn.citations[0]["url"] == "https://voltcart.example/help/doc1"
    assert "content" not in turn.citations[0]


def test_off_topic_skips_retrieval_and_llms():
    spy = Spy([route("off_topic")])
    agent, _ = make_agent(spy, answers=[])
    turn = agent.ask("t", "write a poem")
    assert turn.answer == OFF_TOPIC_REPLY and spy.searched == [] and turn.citations == []


def test_smalltalk_uses_the_chat_model_without_retrieval():
    spy = Spy([route("smalltalk")])
    agent, _ = make_agent(spy, chats=["Hi! How can I help?"])
    turn = agent.ask("t", "hi")
    assert turn.answer == "Hi! How can I help?" and spy.searched == []


def test_failed_relevance_gate_never_calls_the_answer_llm():
    spy = Spy([route("product_info")], gate=False)
    agent, _ = make_agent(spy, answers=[])  # an LLM call would raise: no responses left
    turn = agent.ask("t", "When is the Nova X 2 coming out?")
    assert turn.answer == NO_ANSWER_REPLY and turn.passed_gate is False


# ---------- memory ----------


def test_follow_up_sees_the_previous_turns():
    spy = Spy([route("product_info", "Nova X"), route("product_info", "Nova X price")])
    agent, _ = make_agent(spy, answers=["The Nova X is a phone [1].", "It costs $899 [1]."])

    agent.ask("t", "Tell me about the Nova X")
    agent.ask("t", "how much is it?")

    second = spy.analyzed[1]
    assert [type(m) for m in second] == [HumanMessage, AIMessage, HumanMessage]
    assert second[1].content == "The Nova X is a phone [1]."
    assert spy.searched[1] == "Nova X price"


def test_threads_are_isolated():
    spy = Spy([route("smalltalk"), route("smalltalk")])
    agent, _ = make_agent(spy, chats=["one", "two"])
    agent.ask("a", "hello")
    agent.ask("b", "hello")
    assert len(spy.analyzed[1]) == 1, "thread b must not see thread a's messages"


def test_per_turn_data_is_reset():
    spy = Spy([route("product_info"), route("off_topic")])
    agent, _ = make_agent(spy)
    agent.ask("t", "fee?")
    turn = agent.ask("t", "write a poem")
    assert turn.citations == [] and turn.sources == [] and turn.top_score is None


def test_history_is_limited():
    spy = Spy([route("smalltalk")] * 8)
    agent, _ = make_agent(spy, chats=["ok"] * 8)
    for i in range(8):
        agent.ask("t", f"message {i}")
    assert len(spy.analyzed[-1]) == 10, "only the last 10 messages go to the model"


def test_answer_prompt_contains_rules_date_and_numbered_sources():
    spy = Spy([route("product_info")])
    agent, answer_llm = make_agent(spy)
    agent.ask("t", "fee?")
    system = answer_llm.seen[0][0].content
    assert "Use ONLY the numbered sources" in system and "October 10, 2026" in system
    assert "[1] Returns > Is there a restocking fee? (doc1.html)\n10% on opened" in system


# ---------- citations ----------


def test_extract_citations_dedupes_and_ignores_unknown_numbers():
    sources = [{"n": 1, "heading": "A", "content": "x"}, {"n": 2, "heading": "B", "content": "y"}]
    cited = extract_citations("Fact [2]. Other [1, 2]. Bad [7]. Again [2].", sources)
    assert [c["n"] for c in cited] == [2, 1]


def test_native_model_citations_are_normalized():
    assert normalize_citations("IP68【1†L1-L7】【2】.") == "IP68[1][2]."


# ---------- router ----------


class FakeStructured:
    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), 0

    def invoke(self, messages):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeRouterLLM:
    def __init__(self, outcomes):
        self.structured = FakeStructured(outcomes)

    def with_structured_output(self, schema, method):
        assert schema is Analysis and method == "json_schema"
        return self.structured


def test_router_retries_once_then_succeeds():
    llm = FakeRouterLLM([ValueError("parse failed"), route("order")])
    assert make_analyzer(llm)([HumanMessage("where is it")]).route == "order"
    assert llm.structured.calls == 2


def test_router_falls_back_to_keywords_after_two_failures():
    llm = FakeRouterLLM([ValueError("x"), ValueError("y")])
    result = make_analyzer(llm)([HumanMessage("I want to talk to a real person")])
    assert result.route == "handoff" and llm.structured.calls == 2


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("get me a supervisor", "handoff"),
        ("where is my order?", "order"),
        ("status of VC-10003", "order"),
        ("does the nova x have wireless charging", "product_info"),
    ],
)
def test_fallback_analysis(message, expected):
    assert fallback_analysis(message).route == expected


# ---------- model factory ----------


def test_chat_model_roles_and_missing_key():
    settings = Settings(_env_file=None, groq_api_key="test-key",
                        llm_model_main="groq:openai/gpt-oss-120b",
                        llm_model_small="groq:openai/gpt-oss-20b")  # fmt: skip
    assert get_chat_model("main", settings).model_name == "openai/gpt-oss-120b"
    assert get_chat_model("small", settings).model_name == "openai/gpt-oss-20b"
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        get_chat_model("main", Settings(_env_file=None, groq_api_key=None))


def test_router_without_fallback_raises_instead_of_guessing():
    llm = FakeRouterLLM([ValueError("x"), ValueError("rate limited")])
    with pytest.raises(ValueError, match="rate limited"):
        make_analyzer(llm, fallback=False)([HumanMessage("hi")])


def test_small_model_gets_output_cap_and_reasoning_effort():
    settings = Settings(_env_file=None, groq_api_key="k", llm_model_small="groq:qwen/qwen3.8-27b",
                        llm_small_reasoning_effort="none", llm_small_max_tokens=256)  # fmt: skip
    small = get_chat_model("small", settings)
    assert small.max_tokens == 256 and small.reasoning_effort == "none"
    assert small.max_retries == 0, "fail fast so the backup model takes over"
    main = get_chat_model("main", Settings(_env_file=None, groq_api_key="k"))
    assert main.max_tokens is None and main.reasoning_effort is None


# ---------- persistence (integration) ----------


@pytest.mark.integration
def test_conversation_survives_a_restart_in_postgres():
    """Two separate checkpointer connections = two app restarts: memory must carry over."""
    import uuid

    from langgraph.checkpoint.postgres import PostgresSaver

    from app.config import get_settings

    url, thread = get_settings().psycopg_url, f"test-{uuid.uuid4().hex[:8]}"
    spy = Spy([route("smalltalk"), route("smalltalk")])

    def agent_with(checkpointer, reply):
        graph = build_graph(
            analyze=spy.analyze, retrieve=spy.retrieve,
            answer_llm=FakeListChatModel(responses=["x"]),
            chat_llm=FakeListChatModel(responses=[reply]), checkpointer=checkpointer,
        )  # fmt: skip
        return Agent(graph, Settings(_env_file=None))

    try:
        with PostgresSaver.from_conn_string(url) as saver:
            saver.setup()
            agent_with(saver, "Hi! I'm VoltCart's assistant.").ask(thread, "hello")
        with PostgresSaver.from_conn_string(url) as saver:  # "restarted" app
            agent_with(saver, "Welcome back!").ask(thread, "are you still there?")
        assert [m.content for m in spy.analyzed[1]] == [
            "hello", "Hi! I'm VoltCart's assistant.", "are you still there?",
        ]  # fmt: skip
    finally:
        with PostgresSaver.from_conn_string(url) as saver:
            saver.delete_thread(thread)
