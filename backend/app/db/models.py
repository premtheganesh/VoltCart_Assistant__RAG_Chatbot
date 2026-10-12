"""SQLAlchemy ORM models for the store's structured data.

These tables are accessed through predefined tools (product search, verified order lookup),
never through free-form SQL written by the LLM.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Predictable constraint names, so Alembic migrations can reference them later
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrderStatus(StrEnum):
    PROCESSING = "processing"
    SHIPPED = "shipped"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    RETURN_IN_PROGRESS = "return_in_progress"
    REFUNDED = "refunded"


class ShippingMethod(StrEnum):
    STANDARD = "standard"
    EXPRESS = "express"
    NEXT_DAY = "next_day"


def _in_list(column: str, enum: type[StrEnum]) -> str:
    values = ", ".join(f"'{v.value}'" for v in enum)
    return f"{column} IN ({values})"


class Product(TimestampMixin, Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(50), index=True)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    stock: Mapped[int] = mapped_column(Integer)
    rating: Mapped[Decimal] = mapped_column(Numeric(2, 1))
    review_count: Mapped[int] = mapped_column(Integer)
    short_description: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    colors: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    specs: Mapped[dict] = mapped_column(JSONB, default=dict)

    __table_args__ = (
        CheckConstraint("price_usd >= 0", name="price_non_negative"),
        CheckConstraint("stock >= 0", name="stock_non_negative"),
    )


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Stored lowercase so verification can compare emails case-insensitively
    email: Mapped[str] = mapped_column(String(320), unique=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    city: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(2))

    orders: Mapped[list["Order"]] = relationship(back_populates="customer")


class Order(TimestampMixin, Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_number: Mapped[str] = mapped_column(String(20), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    status: Mapped[str] = mapped_column(String(30))
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    shipping_method: Mapped[str] = mapped_column(String(20))
    shipping_city: Mapped[str] = mapped_column(String(100))
    shipping_state: Mapped[str] = mapped_column(String(2))
    subtotal_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    shipping_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    tax_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    total_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    customer: Mapped[Customer] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    shipment: Mapped["Shipment | None"] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(_in_list("status", OrderStatus), name="valid_status"),
        CheckConstraint(_in_list("shipping_method", ShippingMethod), name="valid_shipping_method"),
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()

    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), unique=True)
    carrier: Mapped[str] = mapped_column(String(20))
    tracking_number: Mapped[str] = mapped_column(String(40))
    shipped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    estimated_delivery: Mapped[date] = mapped_column(Date)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    order: Mapped[Order] = relationship(back_populates="shipment")


# ---------- knowledge base (RAG) ----------

# Must match the embedding model's output size (embed-multilingual-v3.0 = 1024).
# Switching to a model with another size needs a migration and a full re-ingest.
EMBED_DIM = 1024


class Document(Base):
    """One ingested source: a file in sample_data/docs or a catalog product."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Path relative to the project root, or "catalog:<SKU>"
    source: Mapped[str] = mapped_column(String(500), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    doc_type: Mapped[str] = mapped_column(String(30), index=True)
    url: Mapped[str | None] = mapped_column(String(500))
    updated: Mapped[date | None] = mapped_column(Date)
    # sha256 of the raw file (or product text): unchanged hash = skip on re-ingest
    content_hash: Mapped[str] = mapped_column(String(64))
    embed_model: Mapped[str] = mapped_column(String(100))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="Chunk.chunk_index"
    )


class Chunk(Base):
    """A searchable piece of a document, with its embedding and full-text vector."""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    # "Section > Subsection" inside the document ("" for the intro)
    heading: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    page: Mapped[int | None] = mapped_column(Integer)
    # SKUs mentioned in this chunk, for filtering and boosting in retrieval
    products: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    # sha256 of the exact text that was embedded: lets unchanged chunks reuse their vector
    chunk_hash: Mapped[str] = mapped_column(String(64), index=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM))
    embed_model: Mapped[str] = mapped_column(String(100))
    # Postgres keeps this up to date itself; used by keyword (BM25-style) search in Phase 4
    tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', heading || ' ' || content)", persisted=True),
    )

    document: Mapped[Document] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
        Index("ix_chunks_products", "products", postgresql_using="gin"),
    )


# ---------- support ----------


class TicketStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"


class Ticket(TimestampMixin, Base):
    """A request for a human agent, created by the chatbot; worked in the admin inbox."""

    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320))
    summary: Mapped[str] = mapped_column(Text)
    # Why the bot handed off: customer_request, verification_locked, ...
    reason: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default=TicketStatus.OPEN, index=True)
    # Recent messages [{"role": ..., "content": ...}] so the agent needn't ask again
    transcript: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (CheckConstraint(_in_list("status", TicketStatus), name="valid_status"),)

    @property
    def reference(self) -> str:
        return f"T-{self.id:05d}"


class ChatTurn(Base):
    """One question and answer, logged by the API for the admin panel and feedback.
    (LangGraph's checkpoint tables hold the agent's memory; this is the readable record.)"""

    __tablename__ = "chat_turns"

    # 32 hex chars: also the turn's Langfuse trace id, so feedback lands on the right trace
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(100), index=True)
    question: Mapped[str] = mapped_column(Text)  # after PII redaction
    answer: Mapped[str] = mapped_column(Text)
    route: Mapped[str] = mapped_column(String(30))
    citations: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    safety: Mapped[str] = mapped_column(String(20), default="safe")
    top_score: Mapped[float | None] = mapped_column()
    grounded: Mapped[bool | None] = mapped_column()
    latency_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    feedback: Mapped["Feedback | None"] = relationship(
        back_populates="turn", cascade="all, delete-orphan"
    )


class Feedback(TimestampMixin, Base):
    """A customer's thumbs up (1) or down (-1) on one answer, with an optional comment."""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    turn_id: Mapped[str] = mapped_column(
        ForeignKey("chat_turns.id", ondelete="CASCADE"), unique=True
    )
    rating: Mapped[int] = mapped_column(Integer, index=True)
    comment: Mapped[str | None] = mapped_column(Text)

    turn: Mapped[ChatTurn] = relationship(back_populates="feedback")

    __table_args__ = (CheckConstraint("rating IN (-1, 1)", name="valid_rating"),)
