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
from app.db.models import ChatTurn, Feedback
from app.db.session import DbSession, SessionFactory
from app.graph.agent import Agent, Turn
from app.observability import record_feedback

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
    }


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
            events.put(("done", done_event(turn)))
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
