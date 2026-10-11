"""SQLAlchemy ORM models for the store's structured data.

These tables are accessed through predefined tools (product search, verified order lookup),
never through free-form SQL written by the LLM.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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
