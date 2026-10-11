"""Consistency checks on the sample company data (no database needed)."""

import json
import re
from decimal import Decimal

import pytest
from docx import Document
from pypdf import PdfReader

from app.config import PROJECT_ROOT
from scripts.generate_orders import build_orders
from scripts.render_docs import DOCS_DIR, SOURCE_DIR, read_source

DATA = PROJECT_ROOT / "sample_data" / "data"
CATALOG = json.loads((DATA / "catalog.json").read_text())
CUSTOMERS = json.loads((DATA / "customers.json").read_text())
ORDERS = json.loads((DATA / "orders.json").read_text())
SKUS = {p["sku"] for p in CATALOG}

KB_FOLDERS = {
    "manuals": ("manual", 8, ".pdf"),
    "guides": ("buying_guide", 4, ".docx"),
    "helpcenter": ("help_center", 9, ".html"),
}
KB_SOURCES = [p for folder in KB_FOLDERS for p in sorted((SOURCE_DIR / folder).glob("*.md"))]


# ---------- catalog / customers / orders ----------


def test_catalog_has_20_unique_products():
    assert len(CATALOG) == 20
    assert len(SKUS) == 20
    assert {p["category"] for p in CATALOG} == {
        "laptops",
        "audio",
        "phones",
        "smart_home",
        "accessories",
    }


def test_orders_file_matches_generator():
    """orders.json must be regenerated (make generate-orders) if the generator changes."""
    assert build_orders() == ORDERS


def test_orders_reference_known_customers_and_products():
    emails = {c["email"] for c in CUSTOMERS}
    for order in ORDERS:
        assert order["customer_email"] in emails
        assert {i["sku"] for i in order["items"]} <= SKUS


def test_order_totals_add_up():
    for o in ORDERS:
        subtotal = sum(Decimal(i["unit_price_usd"]) * i["quantity"] for i in o["items"])
        assert Decimal(o["subtotal_usd"]) == subtotal
        assert Decimal(o["total_usd"]) == (
            Decimal(o["subtotal_usd"]) + Decimal(o["shipping_usd"]) + Decimal(o["tax_usd"])
        )


def test_shipping_rules_follow_policy():
    for o in ORDERS:
        if o["shipping_state"] in ("AK", "HI"):
            assert (o["shipping_method"], o["shipping_usd"]) == ("standard", "12.99")
        elif o["shipping_method"] == "standard":
            expected = "0.00" if Decimal(o["subtotal_usd"]) >= 35 else "5.99"
            assert o["shipping_usd"] == expected


def test_shipments_match_status():
    for o in ORDERS:
        shipment = o["shipment"]
        if o["status"] in ("processing", "cancelled"):
            assert shipment is None
        else:
            assert shipment is not None
            delivered = o["status"] in ("delivered", "return_in_progress", "refunded")
            assert (shipment["delivered_at"] is not None) == delivered


# ---------- knowledge-base sources ----------


def test_knowledge_base_has_21_sources_plus_test_file():
    for folder, (_, count, _) in KB_FOLDERS.items():
        assert len(list((SOURCE_DIR / folder).glob("*.md"))) == count, folder
    assert (SOURCE_DIR / "test_only" / "returns-and-refunds.md").exists()


@pytest.mark.parametrize("path", KB_SOURCES, ids=lambda p: p.name)
def test_source_front_matter_and_format(path):
    doc = read_source(path)
    expected_type = KB_FOLDERS[path.parent.name][0]

    assert doc.meta["doc_type"] == expected_type
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", doc.meta["updated"])
    listed = {s.strip() for s in doc.meta.get("products", "").split(",") if s.strip()}
    assert listed <= SKUS, f"unknown SKUs: {listed - SKUS}"

    h1s = re.findall(r"^# (.+)$", doc.body, flags=re.M)
    assert h1s == [doc.title]
    assert "```" not in doc.body
    assert not re.search(r"^\s*>", doc.body, flags=re.M), "blockquotes not allowed"
    assert not re.search(r"^\s{2,}[-\d]", doc.body, flags=re.M), "nested lists not allowed"


def test_every_product_appears_in_some_document():
    corpus = " ".join(p.read_text() for p in KB_SOURCES)
    missing = [p["name"] for p in CATALOG if p["name"].split(" (")[0] not in corpus]
    assert not missing, f"products never mentioned in docs: {missing}"


def test_v2_returns_policy_differs_from_v1():
    v1 = (SOURCE_DIR / "helpcenter" / "returns-and-refunds.md").read_text()
    v2 = (SOURCE_DIR / "test_only" / "returns-and-refunds.md").read_text()
    assert "30 days" in v1 and "45 days" in v2
    assert "45 days" not in v1


# ---------- rendered documents ----------


@pytest.mark.parametrize("path", KB_SOURCES, ids=lambda p: p.name)
def test_rendered_document_exists_and_has_title(path):
    """Fails if `make render-docs` wasn't run after editing a source."""
    title = read_source(path).title
    out = DOCS_DIR / f"{path.stem}{KB_FOLDERS[path.parent.name][2]}"

    assert out.exists(), f"missing {out.name}: run make render-docs"
    if out.suffix == ".pdf":
        assert PdfReader(out).metadata.title == title
    elif out.suffix == ".docx":
        assert Document(out).core_properties.title == title
    else:
        assert f"<title>{title.replace('&', '&amp;')} |" in out.read_text()
