"""The agent as a LangGraph state machine.

    START ─► router ─┬─ product_info / recommendation ─► retrieve ─► answer (+ catalog tools) ─► END
                     ├─ order ─────► verify order number + email in code ─► answer from the order
                     ├─ handoff ───► collect contact details ─► create a support ticket
                     ├─ smalltalk ─► short friendly reply
                     └─ off_topic ─► polite refusal

Dependencies (router, retriever, models, tools, database actions) are passed in, so tests can
swap in fakes.
"""

import json
import re
from collections.abc import Callable
from datetime import date

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.types import Checkpointer

from app.graph.prompts import (
    ANSWER_PROMPT,
    ASK_CONTACT,
    ASK_ORDER_DETAILS,
    ASK_ORDER_EMAIL,
    ASK_ORDER_NUMBER,
    MAX_VERIFY_ATTEMPTS,
    NO_ANSWER_REPLY,
    OFF_TOPIC_REPLY,
    ORDER_LOCKED,
    ORDER_NOT_FOUND,
    ORDER_PROMPT,
    SMALLTALK_PROMPT,
    TICKET_CREATED,
    TICKET_EXISTS,
)
from app.graph.state import Analysis, ChatState, Contact
from app.retrieval.retriever import RetrievalResult, RetrievedChunk
from app.tools.orders import find_emails, find_order_numbers

Analyzer = Callable[[list[AnyMessage]], Analysis]
RetrieveFn = Callable[..., RetrievalResult]  # (query, doc_types=None)
OrderLookup = Callable[[str, str], dict | None]  # (order number, email) -> order or None
TicketSaver = Callable[..., str]  # (thread_id=, email=, summary=, reason=, ...) -> "T-00042"
ContactExtractor = Callable[[list[AnyMessage]], Contact]

CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
# Some models (e.g. gpt-oss) cite in their own style: 【1†L1-L7】 or 【2】
NATIVE_CITATION = re.compile(r"【(\d+)(?:†[^】]*)?】")
MAX_TOOL_ROUNDS = 3


def normalize_citations(text: str) -> str:
    return NATIVE_CITATION.sub(r"[\1]", text)


def text_of(message: AnyMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(part.get("text", "") for part in content if isinstance(part, dict))


def conversation(messages: list[AnyMessage], limit: int) -> list[AnyMessage]:
    """The last `limit` customer and assistant messages, text only."""
    turns = [m for m in messages if isinstance(m, HumanMessage | AIMessage) and text_of(m)]
    return [type(m)(content=text_of(m)) for m in turns[-limit:]]


def last_user_text(messages: list[AnyMessage]) -> str:
    return next((text_of(m) for m in reversed(messages) if isinstance(m, HumanMessage)), "")


def chunk_sources(chunks: list[RetrievedChunk], start: int = 1) -> list[dict]:
    return [
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
        for n, c in enumerate(chunks, start=start)
    ]


def product_source(n: int, p: dict) -> dict:
    """A product from a catalog tool, as a numbered source the answer can cite."""
    lines = [
        f"{p['name']} (SKU {p['sku']}): ${p['price_usd']:,.2f}, {p['stock']}, "
        f"rated {p['rating']}/5 from {p['reviews']} reviews.",
        p["description"],
    ]
    if p.get("colors"):
        lines.append(f"Colors: {', '.join(p['colors'])}")
    lines += [f"- {k.replace('_', ' ').capitalize()}: {v}" for k, v in p.get("specs", {}).items()]
    return {
        "n": n,
        "title": p["name"],
        "heading": f"{p['name']} (live catalog)",
        "file": "catalog",
        "source": f"catalog:{p['sku']}",
        "url": None,
        "page": None,
        "score": None,
        "content": "\n".join(lines),
    }


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


def reply(text: str, **updates) -> dict:
    return {"messages": [AIMessage(text)], **updates}


def build_graph(
    *,
    analyze: Analyzer,
    retrieve: RetrieveFn,
    answer_llm: BaseChatModel,
    chat_llm: BaseChatModel,
    lookup_order: OrderLookup | None = None,
    save_ticket: TicketSaver | None = None,
    extract_contact: ContactExtractor | None = None,
    tools: list[BaseTool] | None = None,
    checkpointer: Checkpointer = None,
    history_messages: int = 10,
    today: Callable[[], date] = date.today,
):
    tools = tools or []

    def router(state: ChatState) -> dict:
        message = last_user_text(state["messages"])
        # Per-turn data is reset so nothing from the previous answer leaks into this one
        turn = {"sources": [], "citations": [], "top_score": None, "passed_gate": None}
        awaiting = state.get("awaiting")
        turn["awaiting"] = None
        # The customer is answering our question: no need to ask the LLM where this goes
        if awaiting == "order_email" and find_emails(message):
            return {**turn, "route": "order", "search_query": message}
        if awaiting == "handoff_contact" and find_emails(message):
            return {**turn, "route": "handoff", "search_query": message}
        analysis = analyze(conversation(state["messages"], history_messages))
        return {**turn, "route": analysis.route, "search_query": analysis.search_query}

    def retrieve_node(state: ChatState) -> dict:
        result = retrieve(state["search_query"])
        return {
            "sources": chunk_sources(result.chunks),
            "top_score": result.top_score,
            "passed_gate": result.passed_gate,
        }

    def run_with_tools(messages: list[AnyMessage], sources: list[dict]):
        """Let the model call catalog tools (up to 3 rounds), then answer."""
        if not tools:
            return answer_llm.invoke(messages), sources
        by_name = {t.name: t for t in tools}
        llm = answer_llm.bind_tools(tools)
        messages, sources = list(messages), list(sources)
        for _ in range(MAX_TOOL_ROUNDS):
            response = llm.invoke(messages)
            if not response.tool_calls:
                return response, sources
            messages.append(response)
            for call in response.tool_calls:
                try:
                    products = by_name[call["name"]].invoke(call["args"])
                    new = [product_source(len(sources) + i, p) for i, p in enumerate(products, 1)]
                    sources += new
                    result = "\n\n".join(f"[{s['n']}] {s['content']}" for s in new)
                except Exception as exc:  # bad arguments or unknown tool: tell the model
                    result = f"Tool error: {exc}"
                messages.append(
                    ToolMessage(result or "No matching products.", tool_call_id=call["id"])
                )
        # Out of tool rounds: answer with what we have
        return answer_llm.bind_tools(tools, tool_choice="none").invoke(messages), sources

    def answer(state: ChatState) -> dict:
        if not state.get("passed_gate", True):
            # Relevance gate: nothing relevant found, so don't let the LLM guess
            return reply(NO_ANSWER_REPLY, handoff_reason="no_answer")
        system = ANSWER_PROMPT.format(
            today=today().strftime("%B %d, %Y"), sources=format_sources(state["sources"])
        )
        response, sources = run_with_tools(
            [SystemMessage(system), *conversation(state["messages"], history_messages)],
            state["sources"],
        )
        text = normalize_citations(text_of(response).strip())
        return reply(text, sources=sources, citations=extract_citations(text, sources))

    def order(state: ChatState) -> dict:
        """Verification happens here, in code: the LLM only phrases the answer afterwards."""
        attempts = state.get("verify_attempts") or 0
        if attempts >= MAX_VERIFY_ATTEMPTS:
            return reply(ORDER_LOCKED, handoff_reason="verification_locked")

        message = last_user_text(state["messages"])
        numbers = find_order_numbers(message) or find_order_numbers(state["search_query"])
        number = numbers[0] if numbers else state.get("pending_order")
        emails = find_emails(message)
        verified = dict(state.get("verified_orders") or {})
        # What the customer actually asked: a reply that is just an email must not become the
        # search query for the policy pages
        question = state.get("pending_question") or state["search_query"]

        if number is None:
            return reply(ASK_ORDER_NUMBER if emails else ASK_ORDER_DETAILS)
        if number in verified:
            email = verified[number]  # already verified earlier in this conversation
        elif emails:
            email = emails[0]
        else:
            return reply(
                ASK_ORDER_EMAIL.format(order=number), pending_order=number,
                awaiting="order_email", pending_question=question,
            )  # fmt: skip

        details = lookup_order(number, email)
        if details is None:
            attempts += 1
            if attempts >= MAX_VERIFY_ATTEMPTS:
                return reply(
                    ORDER_LOCKED, verify_attempts=attempts, pending_order=None,
                    pending_question=None, handoff_reason="verification_locked",
                )  # fmt: skip
            left = MAX_VERIFY_ATTEMPTS - attempts
            return reply(
                ORDER_NOT_FOUND.format(left=left, s="" if left == 1 else "s"),
                verify_attempts=attempts, pending_order=number, awaiting="order_email",
                pending_question=question,
            )  # fmt: skip

        verified[number] = email
        # Policy context for "can I still cancel / return it?"
        result = retrieve(question, doc_types=["help_center"])
        sources = chunk_sources(result.chunks)
        system = ORDER_PROMPT.format(
            today=today().strftime("%B %d, %Y"),
            order=json.dumps(details, indent=2),
            sources=format_sources(sources),
        )
        response = answer_llm.invoke(
            [SystemMessage(system), *conversation(state["messages"], history_messages)]
        )
        text = normalize_citations(text_of(response).strip())
        return reply(
            text, verified_orders=verified, pending_order=None, pending_question=None,
            sources=sources, top_score=result.top_score,
            citations=extract_citations(text, sources),
        )  # fmt: skip

    def handoff(state: ChatState, config: RunnableConfig) -> dict:
        if state.get("ticket_ref"):
            return reply(TICKET_EXISTS.format(ref=state["ticket_ref"]))
        convo = conversation(state["messages"], 12)
        user_text = " ".join(text_of(m) for m in convo if isinstance(m, HumanMessage))
        contact = extract_contact(convo)
        # Trust only what the customer actually typed: never an email or name the model invented
        typed = find_emails(user_text)
        email = (contact.email or "").strip().lower()
        email = email if email in typed else (typed[-1] if typed else None)
        name = contact.name if contact.name and contact.name.lower() in user_text.lower() else None
        if email is None:
            return reply(ASK_CONTACT, awaiting="handoff_contact")

        ref = save_ticket(
            thread_id=config["configurable"]["thread_id"],
            name=name,
            email=email,
            summary=contact.summary,
            reason=state.get("handoff_reason") or "customer_request",
            transcript=[
                {
                    "role": "user" if isinstance(m, HumanMessage) else "assistant",
                    "content": text_of(m),
                }
                for m in convo
            ],
        )
        first_name = f", {name.split()[0]}" if name else ""
        return reply(
            TICKET_CREATED.format(name=first_name, ref=ref, email=email),
            ticket_ref=ref, handoff_reason=None,
        )  # fmt: skip

    def smalltalk(state: ChatState) -> dict:
        response = chat_llm.invoke(
            [SystemMessage(SMALLTALK_PROMPT), *conversation(state["messages"], 4)]
        )
        return reply(text_of(response).strip())

    graph = StateGraph(ChatState)
    graph.add_node("router", router)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("answer", answer)
    graph.add_node("order", order)
    graph.add_node("handoff", handoff)
    graph.add_node("smalltalk", smalltalk)
    graph.add_node("off_topic", lambda state: reply(OFF_TOPIC_REPLY))

    graph.add_edge(START, "router")
    graph.add_conditional_edges(
        "router",
        lambda state: state["route"],
        {
            "product_info": "retrieve",
            "recommendation": "retrieve",
            "order": "order",
            "handoff": "handoff",
            "smalltalk": "smalltalk",
            "off_topic": "off_topic",
        },
    )
    graph.add_edge("retrieve", "answer")
    for node in ("answer", "order", "handoff", "smalltalk", "off_topic"):
        graph.add_edge(node, END)
    return graph.compile(checkpointer=checkpointer)
