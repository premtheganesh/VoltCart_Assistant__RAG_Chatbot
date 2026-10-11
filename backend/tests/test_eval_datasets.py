"""Integrity checks for the eval datasets, so evals measure the bot and not dataset mistakes.

Every expected answer must be grounded (sources exist, dollar amounts appear in the documents
or a shown calculation, prices match the catalog), order cases must agree with orders.json,
and unverified order cases must list the order's private details as forbidden output.
"""

import json
import re
from decimal import Decimal

import pytest

from app.config import PROJECT_ROOT
from scripts.render_docs import DOCS_DIR, SOURCE_DIR

DATASETS = PROJECT_ROOT / "evals" / "datasets"
DATA = PROJECT_ROOT / "sample_data" / "data"


def load_jsonl(name: str) -> list[dict]:
    lines = (DATASETS / name).read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


GOLDEN = load_jsonl("golden.jsonl")
ATTACKS = load_jsonl("guardrails.jsonl")
CATALOG = json.loads((DATA / "catalog.json").read_text())
ORDERS = {o["order_number"]: o for o in json.loads((DATA / "orders.json").read_text())}
CUSTOMER_EMAILS = {o["customer_email"] for o in ORDERS.values()}
DOC_NAMES = {p.name for p in DOCS_DIR.iterdir() if p.suffix in (".pdf", ".docx", ".html")}

CATEGORIES = {
    "product_info": 20,
    "comparison": 5,
    "recommendation": 10,
    "policy": 20,
    "order": 12,
    "handoff": 3,
    "smalltalk": 2,
    "unanswerable": 5,
    "off_topic": 5,
}
ROUTES = {"product_info", "recommendation", "order", "handoff", "smalltalk", "off_topic"}
BEHAVIORS = {"answer", "clarify", "verify", "not_in_docs", "refuse", "handoff"}
TOOLS = {"search_products", "get_product", "compare_products", "get_order_status", "create_ticket"}
TAGS = {
    "single_hop", "multi_hop", "cross_doc", "table", "procedure", "troubleshooting",
    "numeric", "calculation", "boundary", "temporal", "negation", "false_premise",
    "ambiguous", "near_miss", "vague", "typo", "casual", "long", "multi_question",
    "multi_turn", "follow_up", "topic_switch", "non_english", "no_manual", "unsatisfiable",
    "partial", "out_of_scope", "competitor", "version_trap", "security", "privacy",
    "case_insensitive", "format_variation", "attempt_limit", "not_found",
}  # fmt: skip
GOLDEN_KEYS = {
    "id", "category", "route", "behavior", "history", "question", "expected_answer",
    "expected_sources", "expected_tools", "order_ref", "must_include", "must_not_include",
    "calculation", "tags",
}  # fmt: skip
GOLDEN_REQUIRED = {
    "id", "category", "route", "behavior", "question", "expected_answer",
    "expected_sources", "must_include", "must_not_include", "tags",
}  # fmt: skip

ATTACK_TYPES = {
    "prompt_injection", "system_prompt_leak", "jailbreak", "false_authority",
    "data_exfiltration", "sql_injection", "verification_bypass", "obfuscation", "pii",
    "toxicity", "harmful", "benign",
}  # fmt: skip
ATTACK_BEHAVIORS = {"block", "refuse", "redact", "deescalate", "allow"}
ATTACK_KEYS = {"id", "attack_type", "expected_behavior", "input", "expected_answer",
               "order_ref", "must_not_include"}  # fmt: skip

STATUS_WORDS = {
    "processing": "processing",
    "shipped": "shipped",
    "out_for_delivery": "out for delivery",
    "delivered": "delivered",
    "cancelled": "cancelled",
    "return_in_progress": "return",
    "refunded": "refund",
}
MONEY = re.compile(r"\$(\d[\d,]*(?:\.\d{2})?)")


def ids(items):
    return [i["id"] for i in items]


def amounts(text: str) -> set[Decimal]:
    return {Decimal(m.replace(",", "")) for m in MONEY.findall(text)}


def conversation_text(item: dict) -> str:
    turns = [t["content"] for t in item.get("history", []) if t["role"] == "user"]
    return " ".join([*turns, item.get("question", item.get("input", ""))])


# Dollar amounts the bot may legitimately say: from the knowledge base and the order data
KB_TEXT = " ".join(p.read_text() for p in SOURCE_DIR.glob("*/*.md") if p.parent.name != "test_only")
ORDER_MONEY = {
    Decimal(o[k]) for o in ORDERS.values() for k in ("subtotal_usd", "shipping_usd", "total_usd")
}
GROUNDED_MONEY = amounts(KB_TEXT) | ORDER_MONEY

# "VoltBook Pro 14 ($1,299)" must match the catalog price; also catch short names like "Pulse ANC"
PRICE_PATTERNS = []
for _p in CATALOG:
    _name = _p["name"].split(" (")[0]
    _names = {_name, re.sub(r" (Headphones|Smart Speaker|Laptop Sleeve)$", "", _name)}
    for _n in _names:
        PRICE_PATTERNS.append((re.compile(re.escape(_n) + r"\s*\(\$([\d,.]+)\)"), _p))


# ---------- golden.jsonl: structure ----------


def test_golden_ids_are_unique_and_sequential():
    assert ids(GOLDEN) == [f"g{i:03d}" for i in range(1, len(GOLDEN) + 1)]


@pytest.mark.parametrize("item", GOLDEN, ids=ids(GOLDEN))
def test_golden_item_schema(item):
    assert GOLDEN_REQUIRED <= item.keys() <= GOLDEN_KEYS, item.keys() ^ GOLDEN_REQUIRED
    assert item["category"] in CATEGORIES
    assert item["route"] in ROUTES
    assert item["behavior"] in BEHAVIORS
    assert item["question"].strip() and item["expected_answer"].strip()
    assert item["tags"] and set(item["tags"]) <= TAGS, set(item["tags"]) - TAGS
    assert len(set(item["tags"])) == len(item["tags"])
    assert set(item.get("expected_tools", [])) <= TOOLS


@pytest.mark.parametrize("item", GOLDEN, ids=ids(GOLDEN))
def test_golden_sources_exist_and_fit_behavior(item):
    sources = item["expected_sources"]
    assert len(set(sources)) == len(sources)
    assert set(sources) <= DOC_NAMES, f"unknown docs: {set(sources) - DOC_NAMES}"
    if item["category"] == "off_topic":
        assert sources == [], "off-topic answers must not cite documents"
    if item["behavior"] == "answer" and item["category"] not in ("order", "smalltalk"):
        assert sources, "grounded answers need at least one source document"


@pytest.mark.parametrize("item", GOLDEN, ids=ids(GOLDEN))
def test_golden_must_include_lists_agree_with_expected_answer(item):
    answer = item["expected_answer"].casefold()
    for phrase in item["must_include"]:
        assert phrase.casefold() in answer, f"must_include {phrase!r} not in expected_answer"
    for phrase in item["must_not_include"]:
        assert phrase.casefold() not in answer, f"expected_answer contains forbidden {phrase!r}"


@pytest.mark.parametrize("item", GOLDEN, ids=ids(GOLDEN))
def test_golden_history_is_a_valid_conversation(item):
    history = item.get("history")
    assert (history is not None) == ("multi_turn" in item["tags"])
    if history is None:
        return
    roles = [t["role"] for t in history]
    assert all(t.keys() == {"role", "content"} and t["content"].strip() for t in history)
    # Alternates user/assistant and ends with the assistant, so `question` is the next user turn
    assert roles == ["user", "assistant"] * (len(roles) // 2) and roles


# ---------- golden.jsonl: grounding ----------


@pytest.mark.parametrize("item", GOLDEN, ids=ids(GOLDEN))
def test_golden_dollar_amounts_are_grounded(item):
    allowed = GROUNDED_MONEY | amounts(item.get("calculation", "")) | amounts(item["question"])
    ungrounded = amounts(item["expected_answer"]) - allowed
    assert not ungrounded, f"amounts not in docs/orders/calculation: {ungrounded}"
    if "calculation" in item["tags"]:
        assert item.get("calculation"), "calculation-tagged items must show the arithmetic"


@pytest.mark.parametrize("item", GOLDEN + ATTACKS, ids=ids(GOLDEN + ATTACKS))
def test_product_prices_match_catalog(item):
    for pattern, product in PRICE_PATTERNS:
        for price in pattern.findall(item["expected_answer"]):
            assert Decimal(price.replace(",", "")) == Decimal(str(product["price_usd"])), product[
                "name"
            ]


@pytest.mark.parametrize(
    "item",
    [i for i in GOLDEN if "returns-and-refunds.html" in i["expected_sources"]],
    ids=lambda i: i["id"],
)
def test_returns_answers_forbid_the_unreleased_v2_policy(item):
    assert "45 days" in item["must_not_include"]


# ---------- golden.jsonl: orders and verification ----------


ORDER_ITEMS = [i for i in GOLDEN if i["category"] == "order"]


@pytest.mark.parametrize("item", ORDER_ITEMS, ids=ids(ORDER_ITEMS))
def test_order_items_agree_with_order_data(item):
    assert item["route"] == "order"
    assert "expected_tools" in item
    ref = item.get("order_ref")
    if ref is None:  # no specific order: bot must ask for the order number
        assert item["behavior"] == "verify"
        return

    text = conversation_text(item).casefold()
    if ref not in ORDERS:
        assert item["behavior"] == "verify" and "not_found" in item["tags"]
        return

    order = ORDERS[ref]
    owner_email = order["customer_email"]
    if item["behavior"] == "answer":
        assert owner_email in text, "a verified answer needs the owner's email in the conversation"
        assert STATUS_WORDS[order["status"]] in item["expected_answer"].casefold()
        assert "get_order_status" in item["expected_tools"]
    elif item["behavior"] == "verify":
        assert owner_email not in text, "owner's email was given, so the bot should answer"
    else:
        assert item["behavior"] == "handoff" and "attempt_limit" in item["tags"]


def test_order_cases_cover_every_status_and_failure_mode():
    answered = {
        ORDERS[i["order_ref"]]["status"]
        for i in ORDER_ITEMS
        if i["behavior"] == "answer" and i.get("order_ref") in ORDERS
    }
    assert answered == set(STATUS_WORDS), f"untested statuses: {set(STATUS_WORDS) - answered}"
    tags = {t for i in ORDER_ITEMS for t in i["tags"]}
    assert {"not_found", "attempt_limit", "case_insensitive", "format_variation"} <= tags
    wrong_email = [
        i
        for i in ORDER_ITEMS
        if i["behavior"] == "verify"
        and i.get("order_ref") in ORDERS
        and any(e in conversation_text(i) for e in CUSTOMER_EMAILS)
    ]
    assert wrong_email, "need a case where a real customer's email is used on someone else's order"


@pytest.mark.parametrize("item", GOLDEN + ATTACKS, ids=ids(GOLDEN + ATTACKS))
def test_unverified_cases_forbid_leaking_order_details(item):
    behavior = item.get("behavior", item.get("expected_behavior"))
    order = ORDERS.get(item.get("order_ref"))
    if order and behavior not in ("answer", "allow"):
        assert order["total_usd"] in item["must_not_include"]
        if order["shipment"]:
            assert order["shipment"]["tracking_number"] in item["must_not_include"]


@pytest.mark.parametrize("item", GOLDEN + ATTACKS, ids=ids(GOLDEN + ATTACKS))
def test_expected_answers_only_reveal_the_verified_order(item):
    behavior = item.get("behavior", item.get("expected_behavior"))
    for number, order in ORDERS.items():
        tracking = (order["shipment"] or {}).get("tracking_number")
        if tracking and tracking in item["expected_answer"]:
            assert item.get("order_ref") == number and behavior in ("answer", "allow")


# ---------- golden.jsonl: coverage ----------


def test_golden_covers_every_document():
    cited = {s for i in GOLDEN for s in i["expected_sources"]}
    assert DOC_NAMES - cited == set(), f"documents never tested: {DOC_NAMES - cited}"


def test_golden_category_minimums():
    counts = {c: sum(i["category"] == c for i in GOLDEN) for c in CATEGORIES}
    short = {c: n for c, n in counts.items() if n < CATEGORIES[c]}
    assert not short, f"categories below minimum: {short}"


def test_golden_uses_every_route_behavior_and_tag():
    assert {i["route"] for i in GOLDEN} == ROUTES
    assert {i["behavior"] for i in GOLDEN} == BEHAVIORS
    used = {t for i in GOLDEN for t in i["tags"]}
    assert TAGS - used == set(), f"edge cases never tested: {TAGS - used}"


def test_golden_questions_are_unique():
    questions = [i["question"].casefold().strip() for i in GOLDEN if "history" not in i]
    assert len(questions) == len(set(questions))


# ---------- guardrails.jsonl ----------


def test_attack_ids_are_unique_and_sequential():
    assert ids(ATTACKS) == [f"a{i:03d}" for i in range(1, len(ATTACKS) + 1)]


@pytest.mark.parametrize("item", ATTACKS, ids=ids(ATTACKS))
def test_attack_item_schema(item):
    assert {"id", "attack_type", "expected_behavior", "input", "expected_answer"} <= item.keys()
    assert item.keys() <= ATTACK_KEYS
    assert item["attack_type"] in ATTACK_TYPES
    assert item["expected_behavior"] in ATTACK_BEHAVIORS
    assert (item["attack_type"] == "benign") == (item["expected_behavior"] == "allow")
    answer = item["expected_answer"].casefold()
    for phrase in item["must_not_include"]:
        assert phrase.casefold() not in answer, f"expected_answer contains forbidden {phrase!r}"


@pytest.mark.parametrize(
    "item", [i for i in ATTACKS if i["attack_type"] == "pii"], ids=lambda i: i["id"]
)
def test_pii_attacks_forbid_echoing_the_pii(item):
    assert any(p in item["input"] for p in item["must_not_include"])


def test_attack_set_coverage():
    types = {i["attack_type"] for i in ATTACKS}
    assert types == ATTACK_TYPES, f"missing attack types: {ATTACK_TYPES - types}"
    assert sum(i["attack_type"] != "benign" for i in ATTACKS) >= 20
    assert sum(i["attack_type"] == "benign" for i in ATTACKS) >= 6, "need false-positive checks"
