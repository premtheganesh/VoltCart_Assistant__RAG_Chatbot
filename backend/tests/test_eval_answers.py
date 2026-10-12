"""Answer-eval scoring and the quality gates, without any API calls."""

import pytest

from scripts import eval_all
from scripts.eval_answers import contains, judge_input, summarize


def item(id_="g1", behavior="answer", category="policy", **extra):
    base = {
        "id": id_, "behavior": behavior, "category": category, "question": "q?",
        "expected_answer": "ref", "must_include": [], "must_not_include": [],
    }  # fmt: skip
    return base | extra


def result(answer="A [1].", **extra):
    base = {"answer": answer, "latency_ms": 1000,
            "sources": [{"n": 1, "heading": "H", "file": "f.html", "content": "fact"}]}  # fmt: skip
    return base | extra


def grade(ok=True, correctness=1, claims=()):
    return {"behavior_ok": ok, "correctness": correctness, "reason": "r",
            "claims": [{"claim": c, "supported": s} for c, s in claims]}  # fmt: skip


def test_correctness_counts_only_answer_questions():
    m = summarize({
        "a": (item("a"), result(), grade(correctness=1)),
        "b": (item("b"), result(), grade(correctness=0.5)),
        "c": (item("c", "refuse", "off_topic"), result(), grade(ok=False, correctness=0)),
    })  # fmt: skip
    assert m["correctness"] == 0.75
    assert m["refusal_accuracy"] == 0.0


def test_faithfulness_is_supported_claims_per_answer_and_skips_orders_and_no_claims():
    m = summarize({
        "a": (item("a"), result(), grade(claims=[("x", True), ("y", False)])),
        "b": (item("b"), result(), grade(claims=[("z", True)])),
        "c": (item("c"), result(), grade(claims=[])),  # nothing to check
        "d": (item("d", category="order"), result(), grade(claims=[("s", False)])),
        "e": (item("e", category="smalltalk"), result(sources=[]), grade(claims=[("hi", False)])),
    })  # fmt: skip
    assert m["faithfulness"] == 0.75  # mean of 0.5 and 1.0


def test_verification_bypass_is_a_leak_in_a_verify_case():
    leak = item("v1", "verify", "order", must_not_include=["shipped", "Sofia"])
    safe = item("v2", "verify", "order", must_not_include=["shipped"])
    m = summarize({
        "v1": (leak, result("Your order has SHIPPED."), grade()),
        "v2": (safe, result("Please share the email on the order."), grade()),
    })  # fmt: skip
    assert m["verification_bypasses"] == 1 and m["bypass_ids"] == ["v1"]
    assert m["trap_hits"] == {"v1": ["shipped"]}


def test_contains_ignores_case_spacing_and_non_breaking_hyphens():
    assert contains("Opened  laptops have a 10 % non‑defect fee", "non-defect")
    assert contains("IP68 rated", "ip68")
    assert not contains("IP67", "IP68")


def test_order_replies_are_judged_without_sources():
    prompt = judge_input(item(category="order", behavior="verify"), result())
    assert "SOURCES: (none)" in prompt and "fact" not in prompt
    prompt = judge_input(item(must_include=["30 days"]), result())
    assert "[1] H (f.html)\nfact" in prompt and "KEY FACTS: 30 days" in prompt
    assert "EXPECTED BEHAVIOR (answer)" in prompt


THRESHOLDS = {
    "answers": {"correctness": {"min": 0.8, "label": "C"},
                "verification_bypasses": {"max": 0, "label": "B"}},
    "routing": {"accuracy": {"min": 0.9, "label": "R"}},
}  # fmt: skip


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        (
            {
                "answers": {"correctness": 0.8, "verification_bypasses": 0},
                "routing": {"accuracy": 0.95},
            },
            {"C": True, "B": True, "R": True},
        ),
        (
            {
                "answers": {"correctness": 0.79, "verification_bypasses": 1},
                "routing": {"accuracy": 0.9},
            },
            {"C": False, "B": False, "R": True},
        ),
        ({"answers": None, "routing": {"accuracy": 0.5}}, {"C": None, "B": None, "R": False}),
    ],
)
def test_quality_gates(results, expected):
    rows = eval_all.check(THRESHOLDS, results)
    assert {r["label"]: r["ok"] for r in rows} == expected


def test_caveats_flag_partial_measurements():
    notes = eval_all.caveats({
        "routing": {"scored": 109, "total": 122},
        "guardrails": {"level": "input"},
        "answers": {"sample": "sample", "questions": 40, "not_scored": ["g9"]},
    })  # fmt: skip
    assert len(notes) == 4 and "109 of 122" in notes[0]


def test_smalltalk_is_judged_on_spirit_not_facts():
    prompt = judge_input(item(category="smalltalk"), result(sources=[]))
    assert "spirit of the reference answer" in prompt and "SOURCES: (none)" in prompt


def test_synthetic_drafts_that_repeat_a_golden_question_are_dropped():
    from scripts.generate_synthetic import is_duplicate

    existing = ["Can I swim with the Stride Sport Earbuds?"]
    assert is_duplicate("can i swim with the stride sport earbuds", existing)
    assert not is_duplicate("How long do the Stride earbuds take to charge?", existing)
