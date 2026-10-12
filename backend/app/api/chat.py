"""Customer endpoints: chat (streamed), conversation history, feedback.

POST /chat answers with Server-Sent Events, a standard format for a stream of events over one
HTTP response:

    event: start   data: {"session_id": "...", "message_id": "..."}
    event: token   data: {"text": "The Stride"}        (many: the reply as it's written)
    event: done    data: {"answer": "...", "citations": [...], ...}   (the final reply)
    event: error   data: {"message": "..."}            (instead of done, if something failed)

`done.answer` is authoritative: clients replace the streamed text with it.
"""

import json
import logging
import queue
import threading
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.security import RateLimiter, client_ip
from app.config import get_settings
from app.db.models import ChatTurn, Feedback, Product
from app.db.session import DbSession, SessionFactory
from app.graph.agent import Agent, Turn
from app.graph.prompts import TICKET_CREATED, TICKET_EXISTS
from app.guardrails.pii import redact
from app.ingestion.pipeline import CATALOG_PREFIX, SHORT_NAME
from app.observability import record_feedback
from app.tools import products
from app.tools.tickets import create_ticket

log = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])

# Server-made, random and long: a session id is the key to a conversation (and to orders
# verified in it), so clients can't choose easy-to-guess ones
SESSION_ID = r"^[0-9a-f]{32}$"
CHAT_ERROR = "Sorry, I'm having trouble answering right now. Please try again in a moment."


def get_agent(request: Request) -> Agent:
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "The assistant is starting up or unavailable.")  # fmt: skip
    return agent


@lru_cache
def get_chat_limiter() -> RateLimiter:
    return RateLimiter(get_settings().chat_rate_per_minute)


class ActiveSessions:
    """One reply at a time per conversation: two at once would interleave its memory."""

    def __init__(self):
        self.active: set[str] = set()
        self.lock = threading.Lock()

    def claim(self, session_id: str) -> bool:
        with self.lock:
            if session_id in self.active:
                return False
            self.active.add(session_id)
            return True

    def release(self, session_id: str) -> None:
        with self.lock:
            self.active.discard(session_id)


active_sessions = ActiveSessions()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(
        None, pattern=SESSION_ID, description="Omit to start a new conversation"
    )


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def done_event(turn: Turn) -> dict:
    """What the customer's browser gets: no internal details (scores, safety reasons, queries)."""
    return {
        "message_id": turn.turn_id,
        "answer": turn.answer,
        "citations": turn.citations,
        # The router still classifies a blocked message; the browser needs to know it was blocked
        "route": turn.route if turn.safety == "safe" else "blocked",
        "notice": turn.notice,
        "ticket_ref": turn.ticket_ref,
        "latency_ms": turn.latency_ms,
        "products": [],  # filled in with live catalog data for cited products
    }


MAX_CARDS = 4


def cited_products(sessions, citations: list[dict], answer: str) -> list[dict]:
    """Product cards with live price, stock and rating: products from the catalog the answer
    cites, plus products a cited document is about *and* the answer names (a buying guide
    recommending the Stride Open shows its card; one that only mentions it in passing doesn't)."""
    cited = [c["source"].removeprefix(CATALOG_PREFIX) for c in citations
             if c.get("source", "").startswith(CATALOG_PREFIX)]  # fmt: skip
    tagged = [sku for c in citations for sku in c.get("products") or []]
    candidates = list(dict.fromkeys(cited + tagged))  # unique, in order
    if not candidates:
        return []
    with sessions() as session:
        rows = {
            p.sku: p for p in session.scalars(select(Product).where(Product.sku.in_(candidates)))
        }
    text = answer.lower()
    cards = []
    for sku in candidates:
        p = rows.get(sku)
        named = p is not None and (
            p.name.lower() in text or SHORT_NAME.sub("", p.name).lower() in text
        )
        if p is not None and (sku in cited or named):
            cards.append(products.summary(p))
    return cards[:MAX_CARDS]


def save_turn(sessions, thread_id: str, turn: Turn) -> None:
    with sessions() as session, session.begin():
        session.add(
            ChatTurn(
                id=turn.turn_id, thread_id=thread_id, question=turn.question,
                answer=turn.answer, route=turn.route, citations=turn.citations,
                safety=turn.safety, top_score=turn.top_score, grounded=turn.grounded,
                latency_ms=turn.latency_ms,
                # Set here, not by Postgres' now() (the transaction's start): keeps order exact
                created_at=datetime.now(UTC),
            )
        )  # fmt: skip


@router.post("/chat", response_class=StreamingResponse)
def chat(
    body: ChatRequest,
    request: Request,
    agent: Annotated[Agent, Depends(get_agent)],
    sessions: SessionFactory,
    limiter: Annotated[RateLimiter, Depends(get_chat_limiter)],
) -> StreamingResponse:
    limiter.check(client_ip(request))
    session_id = body.session_id or uuid.uuid4().hex
    if not active_sessions.claim(session_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Still answering your previous message.")
    turn_id = uuid.uuid4().hex
    events: queue.Queue = queue.Queue()

    def work() -> None:
        """Runs the whole turn in one thread. If the customer closes the page mid-answer, the
        turn still finishes, so the conversation's memory and log stay complete."""
        try:
            streamed = False
            for kind, data in agent.stream(session_id, body.message, turn_id):
                if kind == "token":
                    streamed = True
                    events.put(("token", {"text": data}))
                else:
                    turn = data
            if not streamed:  # a fixed reply: send it as one piece, so clients handle one path
                events.put(("token", {"text": turn.answer}))
            try:
                save_turn(sessions, session_id, turn)
            except Exception:  # the customer still gets the answer; only the log entry is lost
                log.exception("could not save chat turn %s", turn_id)
            done = done_event(turn)
            try:
                done["products"] = cited_products(sessions, turn.citations, turn.answer)
            except Exception:  # cards are a nice-to-have: the answer already has the facts
                log.exception("could not load product cards")
            events.put(("done", done))
        except Exception:
            log.exception("chat turn %s failed", turn_id)
            events.put(("error", {"message": CHAT_ERROR}))
        finally:
            active_sessions.release(session_id)
            events.put(None)

    threading.Thread(target=work, name=f"chat-{turn_id[:8]}", daemon=True).start()

    def stream():
        yield sse("start", {"session_id": session_id, "message_id": turn_id})
        while (item := events.get()) is not None:
            yield sse(*item)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        # Don't let proxies buffer or cache the stream (nginx would hold tokens back otherwise)
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class HistoryItem(BaseModel):
    message_id: str
    question: str
    answer: str
    citations: list[dict]
    rating: int | None


@router.get("/chat/{session_id}/history")
def history(session_id: Annotated[str, Field(pattern=SESSION_ID)], session: DbSession
            ) -> list[HistoryItem]:  # fmt: skip
    """The conversation so far, to redraw it after a page reload."""
    turns = session.scalars(
        select(ChatTurn).where(ChatTurn.thread_id == session_id).order_by(ChatTurn.created_at)
    )
    return [
        HistoryItem(
            message_id=t.id,
            question=t.question,
            answer=t.answer,
            citations=t.citations,
            rating=t.feedback.rating if t.feedback else None,
        )  # fmt: skip
        for t in turns
    ]


class FeedbackRequest(BaseModel):
    session_id: str = Field(pattern=SESSION_ID)
    message_id: str = Field(pattern=SESSION_ID)
    rating: Literal[1, -1]
    comment: str | None = Field(None, max_length=1000)


@router.post("/feedback", status_code=status.HTTP_204_NO_CONTENT)
def feedback(body: FeedbackRequest, session: DbSession) -> None:
    """Thumbs up/down on one answer. Sending again changes the rating."""
    turn = session.get(ChatTurn, body.message_id)
    # Only the conversation's own visitor can rate its answers
    if turn is None or turn.thread_id != body.session_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found.")
    if turn.feedback is None:
        turn.feedback = Feedback(rating=body.rating, comment=body.comment)
    else:
        turn.feedback.rating, turn.feedback.comment = body.rating, body.comment
    session.commit()
    record_feedback(turn.id, body.rating, body.comment)


class HandoffRequest(BaseModel):
    session_id: str = Field(pattern=SESSION_ID)
    email: str = Field(max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    name: str | None = Field(None, max_length=200)
    message: str = Field(min_length=1, max_length=2000)


class HandoffResponse(BaseModel):
    ticket_ref: str
    message: str
    created: bool  # False: this conversation already had a ticket


@router.post("/handoff")
def handoff(
    body: HandoffRequest,
    request: Request,
    agent: Annotated[Agent, Depends(get_agent)],
    session: DbSession,
    limiter: Annotated[RateLimiter, Depends(get_chat_limiter)],
) -> HandoffResponse:
    """The "talk to a human" form: creates a support ticket with the chat so far, no LLM."""
    limiter.check(client_ip(request))
    if not active_sessions.claim(body.session_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Still answering your previous message.")
    try:
        state = agent.state(body.session_id)
        if ref := state.get("ticket_ref"):
            return HandoffResponse(ticket_ref=ref, message=TICKET_EXISTS.format(ref=ref),
                                   created=False)  # fmt: skip
        turns = session.scalars(
            select(ChatTurn).where(ChatTurn.thread_id == body.session_id)
            .order_by(ChatTurn.created_at.desc()).limit(6)
        ).all()  # fmt: skip
        transcript = [
            {"role": role, "content": text}
            for t in reversed(turns)
            for role, text in (("user", t.question), ("assistant", t.answer))
        ]
        message = redact(body.message).text  # no card numbers in the ticket either
        name = (body.name or "").strip() or None
        ref = create_ticket(
            session, thread_id=body.session_id, name=name, email=body.email,
            summary=message, reason=state.get("handoff_reason") or "customer_request",
            transcript=transcript,
        )  # fmt: skip
        reply = TICKET_CREATED.format(
            name=f", {name.split()[0]}" if name else "", ref=ref, email=body.email.lower()
        )
        session.add(
            ChatTurn(
                id=uuid.uuid4().hex, thread_id=body.session_id,
                question=f"(contact form) {message}", answer=reply, route="handoff",
                citations=[], latency_ms=0, created_at=datetime.now(UTC),
            )
        )  # fmt: skip
        session.commit()
        try:
            agent.record_handoff(body.session_id, ref, reply)
        except Exception:  # the ticket exists; the bot just won't know about it in this chat
            log.exception("could not add ticket %s to the conversation", ref)
        return HandoffResponse(ticket_ref=ref, message=reply, created=True)
    finally:
        active_sessions.release(body.session_id)
