"""Tools against the real seeded store data (read-only; ticket writes are rolled back)."""

import pytest
from sqlalchemy import select

from app.db.models import Ticket
from app.tools.orders import find_emails, find_order_numbers, verify_order
from app.tools.products import compare_products, get_product, search_products, stock_label
from app.tools.tickets import create_ticket
from tests.test_ingest import session  # noqa: F401  (rolled-back DB session fixture)

pytestmark = pytest.mark.integration


# ---------- products ----------


def test_search_by_category_and_budget(session):  # noqa: F811
    results = search_products(session, category="audio", max_price=150, sort="price_low")
    assert [p["name"] for p in results] == [
        "Echo Lite Headphones", "Stride Sport Earbuds", "Stride Open",
    ]  # fmt: skip
    assert all(p["price_usd"] <= 150 and p["category"] == "audio" for p in results)


def test_search_keywords_match_specs_and_tags(session):  # noqa: F811
    names = {p["name"] for p in search_products(session, keywords="IP68")}
    assert {"Stride Sport Earbuds", "Nova X", "Nova X Pro"} <= names
    assert "Echo Lite Headphones" not in names


def test_search_limit_is_capped(session):  # noqa: F811
    assert len(search_products(session, limit=500)) == 10


def test_get_product_by_sku_name_or_partial_name(session):  # noqa: F811
    assert get_product(session, "vb-pro16")["name"] == "VoltBook Pro 16"
    assert get_product(session, "pulse anc")["sku"] == "AU-PULSEANC"
    assert get_product(session, "Nova X")["sku"] == "PH-NOVAX", "exact name beats Nova X Pro"
    assert get_product(session, "Dell XPS") is None
    assert "specs" in get_product(session, "VB-AIR14")


def test_compare_keeps_order_and_skips_unknowns_and_duplicates(session):  # noqa: F811
    result = compare_products(session, ["Nova X Pro", "Nova X", "iPhone", "PH-NOVAX"])
    assert [p["sku"] for p in result] == ["PH-NOVAXPRO", "PH-NOVAX"]


def test_stock_labels():
    assert stock_label(0) == "out of stock"
    assert stock_label(3) == "low stock (3 left)"
    assert stock_label(42) == "in stock"


# ---------- orders ----------


def test_verify_order_needs_the_matching_email(session):  # noqa: F811
    order = verify_order(session, "VC-10003", "Sofia.Ramirez@example.com ")
    assert order["status"] == "shipped"
    assert order["shipment"]["tracking_number"] == "790757033266"
    assert verify_order(session, "VC-10003", "maya.patel@example.com") is None
    assert verify_order(session, "VC-99999", "maya.patel@example.com") is None


def test_verified_order_contains_no_customer_identity(session):  # noqa: F811
    order = verify_order(session, "vc-10001", "maya.patel@example.com")
    text = str(order).lower()
    assert "maya" not in text and "@" not in text and "patel" not in text
    assert order["items"] == [
        {"name": "Pulse ANC Headphones", "quantity": 1, "unit_price": "$249.00"}
    ]


def test_unshipped_order_has_no_shipment(session):  # noqa: F811
    order = verify_order(session, "VC-10017", "ava.johnson@example.com")
    assert order["status"] == "processing" and order["shipment"] is None


def test_sql_injection_attempts_find_nothing(session):  # noqa: F811
    assert verify_order(session, "VC-10001' OR '1'='1", "x@x.com") is None
    assert verify_order(session, "VC-10003", "' OR 1=1; DROP TABLE orders; --") is None
    assert verify_order(session, "VC-10003", "sofia.ramirez@example.com") is not None


def test_order_number_and_email_parsing():
    assert find_order_numbers("VC-10003 or vc10001, order #10017") == [
        "VC-10003", "VC-10001", "VC-10017",
    ]  # fmt: skip
    assert find_order_numbers("16 GB, 10000 mAh, $12999") == []
    assert find_emails("Mail Ana.L@Example.com.") == ["ana.l@example.com"]


# ---------- tickets ----------


def test_create_ticket_stores_everything(session):  # noqa: F811
    ref = create_ticket(
        session, thread_id="t-1", email=" Ana@Example.com", summary="Screen flickers.",
        reason="customer_request", name="Ana", transcript=[{"role": "user", "content": "hi"}],
    )  # fmt: skip
    ticket = session.scalar(select(Ticket).where(Ticket.thread_id == "t-1"))
    assert ref == ticket.reference and ref.startswith("T-")
    assert (ticket.email, ticket.status, ticket.reason) == (
        "ana@example.com",
        "open",
        "customer_request",
    )
    assert ticket.transcript == [{"role": "user", "content": "hi"}]
