"""Admin endpoints (all but /admin/login need an admin token): knowledge documents, re-index,
support tickets, conversations and feedback."""

import logging
import re
import shutil
import tempfile
import threading
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.api.security import (
    AdminUser,
    RateLimiter,
    check_password,
    client_ip,
    create_token,
)
from app.config import PROJECT_ROOT, Settings, get_settings
from app.db.models import ChatTurn, Chunk, Document, Feedback, Ticket, TicketStatus
from app.db.session import DbSession
from app.ingestion.loaders import LOADERS, load_file
from app.ingestion.pipeline import CATALOG_PREFIX, IngestReport, ingest
from app.llm.embeddings import embed_model_id, get_embedder

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])
SettingsDep = Annotated[Settings, Depends(get_settings)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]
# Document sources are paths relative to this folder (tests point it at a temporary one)
SOURCE_ROOT = PROJECT_ROOT


@lru_cache
def get_login_limiter() -> RateLimiter:
    return RateLimiter(get_settings().login_rate_per_minute)


# ---------- login ----------


class LoginRequest(BaseModel):
    password: str = Field(max_length=200)


class LoginResponse(BaseModel):
    token: str
    expires_in: int  # seconds


@router.post("/login")
def login(
    body: LoginRequest,
    request: Request,
    settings: SettingsDep,
    limiter: Annotated[RateLimiter, Depends(get_login_limiter)],
) -> LoginResponse:
    limiter.check(client_ip(request))  # 5 guesses a minute makes guessing hopeless
    if not check_password(body.password, settings):
        log.warning("failed admin login from %s", client_ip(request))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong password.")
    return LoginResponse(token=create_token(settings),
                         expires_in=settings.admin_token_hours * 3600)  # fmt: skip


# ---------- documents ----------


class DocumentOut(BaseModel):
    id: int
    source: str
    title: str
    doc_type: str
    chunks: int
    updated: str | None
    ingested_at: datetime
    deletable: bool  # catalog entries come from the products table, not a file


class IngestResult(BaseModel):
    added: list[str]
    updated: list[str]
    deleted: list[str]
    unchanged: int
    chunks_embedded: int
    embed_calls: int


def ingest_result(report: IngestReport) -> IngestResult:
    return IngestResult(
        added=report.added, updated=report.updated, deleted=report.deleted,
        unchanged=len(report.unchanged), chunks_embedded=report.chunks_embedded,
        embed_calls=report.embed_calls,
    )  # fmt: skip


# One ingest at a time: two would race to write the same documents
ingest_lock = threading.Lock()


def run_ingest(session: Session, settings: Settings, force: bool = False) -> IngestReport:
    """Incremental ingest of the whole knowledge base: only new or changed sources are embedded,
    and documents whose file is gone are removed."""
    if not ingest_lock.acquire(blocking=False):
        raise HTTPException(status.HTTP_409_CONFLICT, "Another re-index is running. Try again.")
    try:
        with session.begin():
            return ingest(
                session, get_embedder(settings), embed_model_id(settings),
                SOURCE_ROOT / settings.docs_dir, source_root=SOURCE_ROOT, force=force,
                max_tokens=settings.chunk_max_tokens,
                overlap_tokens=settings.chunk_overlap_tokens,
                batch_size=settings.embed_batch_size,
            )  # fmt: skip
    finally:
        ingest_lock.release()


@router.get("/documents")
def list_documents(_: AdminUser, session: DbSession) -> list[DocumentOut]:
    rows = session.execute(
        select(Document, func.count(Chunk.id))
        .outerjoin(Chunk)
        .group_by(Document.id)
        .order_by(Document.doc_type, Document.title)
    )
    return [
        DocumentOut(
            id=d.id,
            source=d.source,
            title=d.title,
            doc_type=d.doc_type,
            chunks=n,
            updated=d.updated.isoformat() if d.updated else None,
            ingested_at=d.ingested_at,
            deletable=not d.source.startswith(CATALOG_PREFIX),
        )  # fmt: skip
        for d, n in rows
    ]


SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str | None) -> str:
    """Keep only the file's own name, in safe characters: "../../etc/passwd" can't escape the
    uploads folder."""
    stem, suffix = Path(Path(name or "").name).stem, Path(name or "").suffix.lower()
    stem = SAFE_NAME.sub("-", stem).strip("-.")[:100]
    if suffix not in LOADERS:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            f"Upload a {', '.join(sorted(LOADERS))} file.")  # fmt: skip
    if not stem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file needs a name.")
    return stem + suffix


@router.post("/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile, _: AdminUser, session: DbSession, settings: SettingsDep
) -> IngestResult:
    """Add (or replace) a PDF, DOCX or HTML document; it's answerable as soon as this returns."""
    name = safe_filename(file.filename)
    limit = settings.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE,
                            f"Files can be up to {settings.max_upload_mb} MB.")  # fmt: skip
    uploads = SOURCE_ROOT / settings.uploads_dir
    target = uploads / name
    return await run_in_threadpool(_store_and_ingest, data, target, session, settings)


def _store_and_ingest(data: bytes, target: Path, session: Session, settings: Settings):
    # Parse it first, from a temporary copy: a broken file never reaches the knowledge base
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / target.name
        probe.write_bytes(data)
        try:
            parsed = load_file(probe, target.name)
        except Exception as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                f"Couldn't read this file: {exc}") from exc  # fmt: skip
        if not parsed.blocks:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                "No text found (is it a scanned PDF?).")  # fmt: skip
        previous = target.read_bytes() if target.exists() else None
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(probe, target)
    try:
        return ingest_result(run_ingest(session, settings))
    except Exception as exc:
        # Ingest failed (e.g. the embedding API is down): put the folder back as it was
        if previous is None:
            target.unlink(missing_ok=True)
        else:
            target.write_bytes(previous)
        if isinstance(exc, HTTPException):
            raise
        log.exception("ingest after upload failed")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            "Saved nothing: indexing failed (embedding service?). "
                            "Try again.") from exc  # fmt: skip


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: int, _: AdminUser, session: DbSession, settings: SettingsDep
) -> None:
    """Remove a document and its file: it stops being used in answers immediately."""
    doc = session.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")
    if doc.source.startswith(CATALOG_PREFIX):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Catalog entries mirror the products table: change the product "
                            "there instead.")  # fmt: skip
    path = (SOURCE_ROOT / doc.source).resolve()
    docs_dir = (SOURCE_ROOT / settings.docs_dir).resolve()
    if not path.is_relative_to(docs_dir):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Document is outside the docs folder.")
    session.delete(doc)  # its chunks go with it (cascade)
    session.commit()
    # The file too, or the next ingest would add it back
    path.unlink(missing_ok=True)


class ReindexRequest(BaseModel):
    force: bool = Field(False, description="Re-embed everything (after changing EMBED_MODEL)")


@router.post("/reindex")
def reindex(
    _: AdminUser, session: DbSession, settings: SettingsDep, body: ReindexRequest | None = None
) -> IngestResult:
    """Sync the knowledge base with the docs folder and catalog (same as `make ingest`)."""
    try:
        return ingest_result(run_ingest(session, settings, force=bool(body and body.force)))
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("re-index failed")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            "Re-index failed (embedding service?). Nothing was changed."
                            ) from exc  # fmt: skip


# ---------- tickets ----------


class TicketOut(BaseModel):
    id: int
    reference: str
    status: str
    reason: str
    name: str | None
    email: str
    summary: str
    thread_id: str
    created_at: datetime
    updated_at: datetime


class TicketDetail(TicketOut):
    transcript: list[dict]


def ticket_out(t: Ticket, model=TicketOut):
    fields = {k: getattr(t, k) for k in model.model_fields}
    return model(**fields)


@router.get("/tickets")
def list_tickets(
    _: AdminUser, session: DbSession, status_: Annotated[TicketStatus | None,
    Query(alias="status")] = None, limit: Limit = 50, offset: Offset = 0,
) -> list[TicketOut]:  # fmt: skip
    query = (
        select(Ticket)
        .order_by(Ticket.created_at.desc(), Ticket.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if status_:
        query = query.where(Ticket.status == status_)
    return [ticket_out(t) for t in session.scalars(query)]


@router.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: int, _: AdminUser, session: DbSession) -> TicketDetail:
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found.")
    return ticket_out(ticket, TicketDetail)


class TicketUpdate(BaseModel):
    status: TicketStatus


@router.patch("/tickets/{ticket_id}")
def update_ticket(
    ticket_id: int, body: TicketUpdate, _: AdminUser, session: DbSession
) -> TicketOut:
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found.")
    ticket.status = body.status
    session.commit()
    session.refresh(ticket)
    return ticket_out(ticket)


# ---------- conversations + feedback ----------


class ConversationOut(BaseModel):
    thread_id: str
    turns: int
    first_question: str
    started_at: datetime
    last_at: datetime
    thumbs_down: int


@router.get("/conversations")
def list_conversations(
    _: AdminUser, session: DbSession, limit: Limit = 50, offset: Offset = 0
) -> list[ConversationOut]:
    rows = session.execute(
        select(
            ChatTurn.thread_id,
            func.count(ChatTurn.id),
            func.min(ChatTurn.created_at),
            func.max(ChatTurn.created_at),
            func.count(Feedback.id).filter(Feedback.rating == -1),
        )
        .outerjoin(Feedback)
        .group_by(ChatTurn.thread_id)
        .order_by(func.max(ChatTurn.created_at).desc())
        .limit(limit)
        .offset(offset)
    ).all()
    # Each conversation's first question (DISTINCT ON keeps the earliest row per thread)
    firsts = dict(
        session.execute(
            select(ChatTurn.thread_id, ChatTurn.question)
            .where(ChatTurn.thread_id.in_([r[0] for r in rows]))
            .ext(distinct_on(ChatTurn.thread_id))
            .order_by(ChatTurn.thread_id, ChatTurn.created_at)
        ).all()
    )
    return [
        ConversationOut(
            thread_id=t,
            turns=n,
            first_question=firsts.get(t, ""),
            started_at=s,
            last_at=last,
            thumbs_down=down,
        )  # fmt: skip
        for t, n, s, last, down in rows
    ]


class TurnOut(BaseModel):
    message_id: str
    question: str
    answer: str
    route: str
    citations: list[dict]
    safety: str
    top_score: float | None
    grounded: bool | None
    latency_ms: int
    created_at: datetime
    rating: int | None
    comment: str | None


def turn_out(t: ChatTurn) -> TurnOut:
    return TurnOut(
        message_id=t.id, question=t.question, answer=t.answer, route=t.route,
        citations=t.citations, safety=t.safety, top_score=t.top_score, grounded=t.grounded,
        latency_ms=t.latency_ms, created_at=t.created_at,
        rating=t.feedback.rating if t.feedback else None,
        comment=t.feedback.comment if t.feedback else None,
    )  # fmt: skip


@router.get("/conversations/{thread_id}")
def get_conversation(thread_id: str, _: AdminUser, session: DbSession) -> list[TurnOut]:
    turns = list(session.scalars(
        select(ChatTurn).where(ChatTurn.thread_id == thread_id).order_by(ChatTurn.created_at)
    ))  # fmt: skip
    if not turns:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found.")
    return [turn_out(t) for t in turns]


class FeedbackOut(TurnOut):
    thread_id: str


@router.get("/feedback")
def list_feedback(
    _: AdminUser, session: DbSession,
    rating: Annotated[int | None, Query(description="1 or -1; omit for both")] = None,
    limit: Limit = 50, offset: Offset = 0,
) -> list[FeedbackOut]:  # fmt: skip
    """Rated answers, newest first. rating=-1 is the to-do list for improving the bot."""
    query = (
        select(ChatTurn).join(Feedback).order_by(Feedback.created_at.desc())
        .limit(limit).offset(offset)
    )  # fmt: skip
    if rating is not None:
        query = query.where(Feedback.rating == rating)
    return [
        FeedbackOut(**turn_out(t).model_dump(), thread_id=t.thread_id)
        for t in session.scalars(query)
    ]
