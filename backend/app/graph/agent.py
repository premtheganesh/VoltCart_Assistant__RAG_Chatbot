"""Wire the graph to real models, retrieval, Postgres memory and Langfuse tracing.

with open_agent() as agent:
    turn = agent.ask("thread-1", "Can I swim with the Stride earbuds?")
    print(turn.answer, turn.citations)
"""

import logging
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import get_engine
from app.graph.builder import Analyzer, RetrieveFn, build_graph, text_of
from app.graph.prompts import ROUTER_PROMPT
from app.graph.state import Analysis
from app.llm.chat import get_chat_model
from app.llm.embeddings import get_embedder
from app.observability import get_langfuse_handler
from app.retrieval.reranker import get_reranker
from app.retrieval.retriever import RetrievalResult, Retriever

log = logging.getLogger(__name__)


def make_analyzer(llm: BaseChatModel, *, fallback: bool = True) -> Analyzer:
    """fallback=False raises instead of guessing (evals must not score a guess as the model's)."""
    structured = llm.with_structured_output(Analysis, method="json_schema")

    def analyze(messages: list[AnyMessage]) -> Analysis:
        prompt = [SystemMessage(ROUTER_PROMPT), *messages]
        # Reasoning models occasionally return their thinking instead of the JSON: retry once
        for attempt in (1, 2):
            try:
                return structured.invoke(prompt)
            except Exception as exc:  # a failed classification must not break the chat
                log.warning("router attempt %d failed: %s", attempt, str(exc)[:200])
                if attempt == 2 and not fallback:
                    raise
        last = next((m for m in reversed(messages) if isinstance(m, HumanMessage)), None)
        return fallback_analysis(text_of(last) if last else "")

    return analyze


HANDOFF_WORDS = re.compile(r"\b(human|real person|agent|supervisor|representative|complain)", re.I)
ORDER_WORDS = re.compile(r"\b(VC-?\d{5}|my order|tracking|where is my)", re.I)


def fallback_analysis(message: str) -> Analysis:
    """Keyword routing for when the router model fails: crude, but never sends a request for a
    human or an order down the document-search path."""
    if HANDOFF_WORDS.search(message):
        return Analysis(route="handoff", search_query=message)
    if ORDER_WORDS.search(message):
        return Analysis(route="order", search_query=message)
    return Analysis(route="product_info", search_query=message)


def make_retrieve(settings: Settings) -> RetrieveFn:
    embedder, reranker = get_embedder(settings), get_reranker(settings)

    def retrieve(query: str) -> RetrievalResult:
        with Session(get_engine()) as session:
            return Retriever(session, embedder, reranker, settings).retrieve(query)

    return retrieve


@dataclass
class Turn:
    answer: str
    route: str
    search_query: str
    citations: list[dict]
    sources: list[dict] = field(default_factory=list)
    top_score: float | None = None
    passed_gate: bool | None = None
    latency_ms: float = 0.0


class Agent:
    def __init__(self, graph, settings: Settings, tracer=None):
        """tracer: a LangChain callback (Langfuse) that records each turn, or None."""
        self.graph, self.settings, self.tracer = graph, settings, tracer

    def ask(self, thread_id: str, message: str) -> Turn:
        config = {
            "configurable": {"thread_id": thread_id},
            "callbacks": [self.tracer] if self.tracer else [],
            "metadata": {"langfuse_session_id": thread_id},  # groups a chat's turns in Langfuse
            "run_name": "voltcart-chat",
        }
        start = time.perf_counter()
        state = self.graph.invoke({"messages": [HumanMessage(message)]}, config)
        return Turn(
            answer=text_of(state["messages"][-1]),
            route=state.get("route", ""),
            search_query=state.get("search_query", ""),
            citations=state.get("citations", []),
            sources=state.get("sources", []),
            top_score=state.get("top_score"),
            passed_gate=state.get("passed_gate"),
            latency_ms=round((time.perf_counter() - start) * 1000),
        )


@contextmanager
def open_agent(settings: Settings | None = None, *, persist: bool = True) -> Iterator[Agent]:
    """persist=True stores conversations in Postgres (survive restarts); False keeps them in
    memory only (tests, throwaway runs)."""
    settings = settings or get_settings()
    deps = dict(
        analyze=make_analyzer(get_chat_model("small", settings)),
        retrieve=make_retrieve(settings),
        answer_llm=get_chat_model("main", settings),
        chat_llm=get_chat_model("small", settings),
        history_messages=settings.history_messages,
    )
    tracer = get_langfuse_handler()
    if not persist:
        yield Agent(build_graph(**deps, checkpointer=InMemorySaver()), settings, tracer)
        return

    from langgraph.checkpoint.postgres import PostgresSaver

    with PostgresSaver.from_conn_string(settings.psycopg_url) as checkpointer:
        checkpointer.setup()  # creates LangGraph's checkpoint tables on first use
        yield Agent(build_graph(**deps, checkpointer=checkpointer), settings, tracer)
