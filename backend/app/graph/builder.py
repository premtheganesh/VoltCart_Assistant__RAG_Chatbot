"""The agent as a LangGraph state machine.

    START ─► router ─┬─ product_info / recommendation ─► retrieve ─► answer ─► END
                     ├─ smalltalk ─► smalltalk ─► END
                     ├─ off_topic ─► off_topic ─► END
                     ├─ order ─────► order ─────► END      (verified lookup in Phase 6)
                     └─ handoff ───► handoff ───► END      (support tickets in Phase 6)

Dependencies (router, retriever, models) are passed in, so tests can swap in fakes.
"""

import re
from collections.abc import Callable
from datetime import date

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Checkpointer

from app.graph.prompts import (
    ANSWER_PROMPT,
    HANDOFF_REPLY,
    NO_ANSWER_REPLY,
    OFF_TOPIC_REPLY,
    ORDER_REPLY,
    SMALLTALK_PROMPT,
)
from app.graph.state import Analysis, ChatState
from app.retrieval.retriever import RetrievalResult

Analyzer = Callable[[list[AnyMessage]], Analysis]
RetrieveFn = Callable[[str], RetrievalResult]

CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
# Some models (e.g. gpt-oss) cite in their own style: 【1†L1-L7】 or 【2】
NATIVE_CITATION = re.compile(r"【(\d+)(?:†[^】]*)?】")


def normalize_citations(text: str) -> str:
    return NATIVE_CITATION.sub(r"[\1]", text)


def text_of(message: AnyMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(part.get("text", "") for part in content if isinstance(part, dict))


def conversation(messages: list[AnyMessage], limit: int) -> list[AnyMessage]:
    """The last `limit` customer and assistant messages, text only."""
    turns = [m for m in messages if isinstance(m, HumanMessage | AIMessage)]
    return [type(m)(content=text_of(m)) for m in turns[-limit:]]


def format_sources(sources: list[dict]) -> str:
    return "\n\n".join(f"[{s['n']}] {s['heading']} ({s['file']})\n{s['content']}" for s in sources)


def extract_citations(answer: str, sources: list[dict]) -> list[dict]:
    """Sources the answer cites, in order of first mention. Numbers with no source are ignored."""
    by_n = {s["n"]: s for s in sources}
    cited: list[int] = []
    for group in CITATION.findall(answer):
        for n in (int(x) for x in group.split(",")):
            if n in by_n and n not in cited:
                cited.append(n)
    return [{k: v for k, v in by_n[n].items() if k != "content"} for n in cited]


def build_graph(
    *,
    analyze: Analyzer,
    retrieve: RetrieveFn,
    answer_llm: BaseChatModel,
    chat_llm: BaseChatModel,
    checkpointer: Checkpointer = None,
    history_messages: int = 10,
    today: Callable[[], date] = date.today,
):
    def router(state: ChatState) -> dict:
        analysis = analyze(conversation(state["messages"], history_messages))
        # Reset per-turn data so nothing from the previous answer leaks into this one
        return {
            "route": analysis.route,
            "search_query": analysis.search_query,
            "sources": [],
            "citations": [],
            "top_score": None,
            "passed_gate": None,
        }

    def retrieve_node(state: ChatState) -> dict:
        result = retrieve(state["search_query"])
        sources = [
            {
                "n": n,
                "title": c.title,
                "heading": c.heading,
                "file": c.file_name,
                "source": c.source,
                "url": c.url,
                "page": c.page,
                "score": round(c.score, 3),
                "content": c.content,
            }
            for n, c in enumerate(result.chunks, start=1)
        ]
        return {
            "sources": sources,
            "top_score": result.top_score,
            "passed_gate": result.passed_gate,
        }

    def answer(state: ChatState) -> dict:
        if not state.get("passed_gate", True):
            # Relevance gate: nothing relevant was found, so don't let the LLM guess
            return {"messages": [AIMessage(NO_ANSWER_REPLY)]}
        system = ANSWER_PROMPT.format(
            today=today().strftime("%B %d, %Y"), sources=format_sources(state["sources"])
        )
        reply = answer_llm.invoke(
            [SystemMessage(system), *conversation(state["messages"], history_messages)]
        )
        text = normalize_citations(text_of(reply).strip())
        return {
            "messages": [AIMessage(text)],
            "citations": extract_citations(text, state["sources"]),
        }

    def smalltalk(state: ChatState) -> dict:
        reply = chat_llm.invoke(
            [SystemMessage(SMALLTALK_PROMPT), *conversation(state["messages"], 4)]
        )
        return {"messages": [AIMessage(text_of(reply).strip())]}

    def fixed(text: str):
        return lambda state: {"messages": [AIMessage(text)]}

    graph = StateGraph(ChatState)
    graph.add_node("router", router)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("answer", answer)
    graph.add_node("smalltalk", smalltalk)
    graph.add_node("off_topic", fixed(OFF_TOPIC_REPLY))
    graph.add_node("order", fixed(ORDER_REPLY))
    graph.add_node("handoff", fixed(HANDOFF_REPLY))

    graph.add_edge(START, "router")
    graph.add_conditional_edges(
        "router",
        lambda state: state["route"],
        {
            "product_info": "retrieve",
            "recommendation": "retrieve",
            "smalltalk": "smalltalk",
            "off_topic": "off_topic",
            "order": "order",
            "handoff": "handoff",
        },
    )
    graph.add_edge("retrieve", "answer")
    for node in ("answer", "smalltalk", "off_topic", "order", "handoff"):
        graph.add_edge(node, END)
    return graph.compile(checkpointer=checkpointer)
