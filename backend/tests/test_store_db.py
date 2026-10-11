"""Read-only checks on the seeded database. Requires: make db-up && make migrate && make seed."""

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.models import Customer, Order, OrderItem, Product, Shipment
from app.db.session import get_engine

pytestmark = pytest.mark.integration


@pytest.fixture
def session():
    with Session(get_engine()) as s:
        yield s


def test_migrations_are_at_head(session):
    version = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert version


@pytest.mark.parametrize(
    ("model", "expected"),
    [(Product, 20), (Customer, 12), (Order, 30), (Shipment, 24)],
)
def test_row_counts(session, model, expected):
    assert session.scalar(select(func.count()).select_from(model)) == expected


def test_every_order_has_items_and_correct_total(session):
    for order in session.scalars(select(Order)):
        assert order.items, order.order_number
        subtotal = sum(i.unit_price_usd * i.quantity for i in order.items)
        assert order.subtotal_usd == subtotal
        assert order.total_usd == order.subtotal_usd + order.shipping_usd + order.tax_usd


def test_order_lookup_by_number_and_email(session):
    """The shape of query the verified order tool will use in Phase 6."""
    order = session.scalars(select(Order).where(Order.order_number == "VC-10001")).one()
    match = session.scalars(
        select(Order)
        .join(Customer)
        .where(Order.order_number == "VC-10001", Customer.email == order.customer.email)
    ).one_or_none()
    wrong = session.scalars(
        select(Order)
        .join(Customer)
        .where(Order.order_number == "VC-10001", Customer.email == "attacker@example.com")
    ).one_or_none()

    assert match is not None
    assert wrong is None


def test_product_specs_are_queryable_as_json(session):
    ip68 = session.scalars(
        select(Product.sku).where(Product.specs["water_resistance"].astext.like("IP68%"))
    ).all()
    assert {"AU-STRIDE", "PH-NOVAX", "PH-NOVAXPRO"} <= set(ip68)


def test_order_items_reference_products(session):
    orphans = session.scalar(
        select(func.count()).select_from(OrderItem).where(OrderItem.product_id.is_(None))
    )
    assert orphans == 0
