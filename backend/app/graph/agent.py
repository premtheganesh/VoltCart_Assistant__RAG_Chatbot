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
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.session import get_engine
from app.graph.builder import Analyzer, ContactExtractor, RetrieveFn, build_graph, text_of
from app.graph.prompts import CONTACT_PROMPT, ROUTER_PROMPT
from app.graph.state import Analysis, Contact
from app.llm.chat import get_chat_model
from app.llm.embeddings import get_embedder
from app.observability import get_langfuse_handler
from app.retrieval.reranker import get_reranker
from app.retrieval.retriever import RetrievalResult, Retriever
from app.tools import products
from app.tools.orders import verify_order
from app.tools.tickets import create_ticket

log = logging.getLogger(__name__)


def structured(llm: BaseChatModel, schema, backup: BaseChatModel | None = None):
    """JSON-schema output from `llm`; if it fails (e.g. out of quota), the same from `backup`."""
    runnable = llm.with_structured_output(schema, method="json_schema")
    if backup is not None:
        runnable = runnable.with_fallbacks(
            [backup.with_structured_output(schema, method="json_schema")]
        )
    return runnable


def make_analyzer(
    llm: BaseChatModel, *, backup: BaseChatModel | None = None, fallback: bool = True
) -> Analyzer:
    """backup: a second model tried when `llm` fails. fallback=False raises instead of guessing
    by keywords (evals must not score a guess as the model's answer)."""
    structured_llm = structured(llm, Analysis, backup)

    def analyze(messages: list[AnyMessage]) -> Analysis:
        prompt = [SystemMessage(ROUTER_PROMPT), *messages]
        # Reasoning models occasionally return their thinking instead of the JSON: retry once
        for attempt in (1, 2):
            try:
                return structured_llm.invoke(prompt)
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

    def retrieve(query: str, doc_types: list[str] | None = None) -> RetrievalResult:
        with Session(get_engine()) as session:
            return Retriever(session, embedder, reranker, settings).retrieve(
                query, doc_types=doc_types
            )

    return retrieve


def make_product_tools() -> list[StructuredTool]:
    """Catalog tools the answer model may call. Each call opens its own short DB session."""

    def search(
        category: products.Category | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        keywords: str | None = None,
        in_stock_only: bool = False,
        sort: products.Sort = "rating",
        limit: int = 5,
    ) -> list[dict]:
        """Find VoltCart products by category, price range in USD and keywords (feature words
        like "noise cancelling", "waterproof", "gaming"). Returns price, stock and rating."""
        with Session(get_engine()) as session:
            return products.search_products(
                session, category=category, min_price=min_price, max_price=max_price,
                keywords=keywords, in_stock_only=in_stock_only, sort=sort, limit=limit,
            )  # fmt: skip

    def get(name_or_sku: str) -> list[dict]:
        """Full specs, colors, live price and stock for one product, by name or SKU."""
        with Session(get_engine()) as session:
            found = products.get_product(session, name_or_sku)
            return [found] if found else []

    def compare(names_or_skus: list[str]) -> list[dict]:
        """Full specs, live prices and stock for 2 to 4 products, to compare side by side."""
        with Session(get_engine()) as session:
            return products.compare_products(session, names_or_skus)

    return [
        StructuredTool.from_function(search, name="search_products"),
        StructuredTool.from_function(get, name="get_product"),
        StructuredTool.from_function(compare, name="compare_products"),
    ]


def lookup_order(order_number: str, email: str) -> dict | None:
    with Session(get_engine()) as session:
        return verify_order(session, order_number, email)


def save_ticket(**fields) -> str:
    with Session(get_engine()) as session, session.begin():
        return create_ticket(session, **fields)


def make_contact_extractor(
    llm: BaseChatModel, backup: BaseChatModel | None = None
) -> ContactExtractor:
    structured_llm = structured(llm, Contact, backup)

    def extract(messages: list[AnyMessage]) -> Contact:
        try:
            return structured_llm.invoke([SystemMessage(CONTACT_PROMPT), *messages])
        except Exception:  # still create the ticket: email comes from what the customer typed
            log.warning("contact extraction failed", exc_info=True)
            said = " ".join(text_of(m) for m in messages if isinstance(m, HumanMessage))
            return Contact(summary=said[-500:] or "Customer asked for a human agent.")

    return extract


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
    small, main = get_chat_model("small", settings), get_chat_model("main", settings)
    deps = dict(
        # Small-model jobs fall back to the main model if the small one fails or is out of quota
        analyze=make_analyzer(small, backup=main),
        retrieve=make_retrieve(settings),
        answer_llm=main,
        chat_llm=small.with_fallbacks([main]),
        lookup_order=lookup_order,
        save_ticket=save_ticket,
        extract_contact=make_contact_extractor(small, backup=main),
        tools=make_product_tools(),
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
