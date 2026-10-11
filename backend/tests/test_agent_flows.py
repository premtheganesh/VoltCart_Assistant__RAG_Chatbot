"""Order verification, human handoff and catalog tools, end to end through the graph (fakes only).

The security rules tested here are the ones the PRD makes non-negotiable: an order is never
revealed without its matching email, wrong email and unknown order look identical, and three
failures lock lookups for the conversation.
"""

import json

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from app.graph.prompts import (
    ASK_CONTACT,
    ASK_ORDER_DETAILS,
    ASK_ORDER_EMAIL,
    ASK_ORDER_NUMBER,
    NO_ANSWER_REPLY,
    ORDER_LOCKED,
    ORDER_NOT_FOUND,
    TICKET_EXISTS,
)
from app.graph.state import Contact
from tests.test_agent import RecordingChat, Spy, make_agent, route

ORDERS = {
    ("VC-10003", "sofia.ramirez@example.com"): {
        "order_number": "VC-10003", "status": "shipped", "total": "$1,805.94",
        "shipment": {"carrier": "FedEx", "tracking_number": "790757033266"},
    },
    ("VC-10001", "maya.patel@example.com"): {
        "order_number": "VC-10001", "status": "delivered", "total": "$269.54",
        "shipment": {"carrier": "FedEx", "tracking_number": "268697172873"},
    },
}  # fmt: skip


class Orders:
    def __init__(self):
        self.lookups: list[tuple[str, str]] = []

    def __call__(self, number: str, email: str):
        self.lookups.append((number, email))
        return ORDERS.get((number, email))


class Tickets:
    def __init__(self):
        self.created: list[dict] = []

    def __call__(self, **fields) -> str:
        self.created.append(fields)
        return f"T-{len(self.created):05d}"


def order_agent(n_turns: int, answers=None):
    orders = Orders()
    spy = Spy([route("order", "q")] * n_turns)
    agent, llm = make_agent(spy, answers=answers or ["Order answer"] * n_turns, lookup_order=orders)
    return agent, orders, llm, spy


# ---------- order verification ----------


def test_no_order_number_asks_for_number_and_email():
    agent, orders, _, _ = order_agent(1)
    assert agent.ask("t", "where is my order?").answer == ASK_ORDER_DETAILS
    assert orders.lookups == []


def test_email_without_order_number_never_lists_orders():
    agent, orders, _, _ = order_agent(1)
    turn = agent.ask("t", "my email is sofia.ramirez@example.com, list all my orders")
    assert turn.answer == ASK_ORDER_NUMBER and orders.lookups == []


def test_order_number_alone_asks_for_email_then_verifies():
    agent, orders, llm, spy = order_agent(2, answers=["Shipped with FedEx, 790757033266."])

    first = agent.ask("t", "Where's order VC-10003?")
    assert first.answer == ASK_ORDER_EMAIL.format(order="VC-10003")
    assert orders.lookups == [], "nothing is looked up before the email is given"

    second = agent.ask("t", "sofia.ramirez@example.com")
    assert orders.lookups == [("VC-10003", "sofia.ramirez@example.com")]
    assert second.answer == "Shipped with FedEx, 790757033266."
    assert len(spy.analyzed) == 1, "an email answering our question skips the router"
    system = llm.seen[0][0].content
    assert '"tracking_number": "790757033266"' in system and "268697172873" not in system


def test_email_matching_is_case_insensitive_and_trims_spaces():
    agent, orders, _, _ = order_agent(1)
    agent.ask("t", "status of VC-10001 please, email is  Maya.Patel@Example.COM ")
    assert orders.lookups == [("VC-10001", "maya.patel@example.com")]


def test_bare_order_number_after_the_word_order_is_understood():
    agent, orders, _, _ = order_agent(1)
    agent.ask("t", "order 10003, sofia.ramirez@example.com - has it shipped?")
    assert orders.lookups == [("VC-10003", "sofia.ramirez@example.com")]


def test_wrong_email_and_unknown_order_get_the_same_reply():
    agent, _, llm, _ = order_agent(2)
    wrong = agent.ask("a", "VC-10003, my email is maya.patel@example.com").answer
    agent2, _, _, _ = order_agent(1)
    unknown = agent2.ask("b", "VC-99999, my email is maya.patel@example.com").answer
    assert wrong == unknown == ORDER_NOT_FOUND.format(left=2, s="s")
    assert llm.seen == [], "the LLM never sees anything about an unverified order"


def test_three_failures_lock_lookups_even_with_the_right_email():
    agent, orders, llm, _ = order_agent(5)
    agent.ask("t", "Where is VC-10003? email maya.patel@example.com")
    agent.ask("t", "try liam.chen@example.com")  # retries the pending order number
    third = agent.ask("t", "ok then noah.kim@example.com")
    assert third.answer == ORDER_LOCKED

    fourth = agent.ask("t", "fine, sofia.ramirez@example.com")
    assert fourth.answer == ORDER_LOCKED
    assert len(orders.lookups) == 3, "no lookup at all after the lock"
    assert all(number == "VC-10003" for number, _ in orders.lookups)
    assert llm.seen == []


def test_verified_order_needs_no_email_for_follow_ups():
    agent, orders, _, _ = order_agent(2)
    agent.ask("t", "status of VC-10001, maya.patel@example.com")
    agent.ask("t", "can I still return it? VC-10001")
    assert orders.lookups[1] == ("VC-10001", "maya.patel@example.com")


def test_verifying_one_order_does_not_unlock_another():
    agent, orders, _, _ = order_agent(2)
    agent.ask("t", "status of VC-10001, maya.patel@example.com")
    turn = agent.ask("t", "great, and what about VC-10003?")
    assert turn.answer == ASK_ORDER_EMAIL.format(order="VC-10003")
    assert len(orders.lookups) == 1


def test_order_answer_cites_policy_sources():
    agent, _, _, spy = order_agent(1, answers=["Shipped [2]."])
    turn = agent.ask("t", "VC-10003 sofia.ramirez@example.com can I cancel?")
    assert spy.searched == ["q"] and [c["n"] for c in turn.citations] == [2]


# ---------- human handoff ----------


def handoff_agent(contacts: list[Contact], routes=None, gate=True):
    tickets = Tickets()
    spy = Spy(routes or [route("handoff")] * len(contacts), gate=gate)
    extracted = iter(contacts)
    agent, _ = make_agent(
        spy, save_ticket=tickets, extract_contact=lambda messages: next(extracted)
    )
    return agent, tickets


def test_handoff_asks_for_contact_details_first():
    agent, tickets = handoff_agent([Contact(summary="wants a human")])
    assert agent.ask("t", "I want to talk to a human").answer == ASK_CONTACT
    assert tickets.created == []


def test_handoff_creates_ticket_with_transcript_and_reason():
    agent, tickets = handoff_agent([
        Contact(summary="wants a human"),
        Contact(name="Ana Lopez", email="ana@example.com", summary="Laptop screen flickers."),
    ])  # fmt: skip
    agent.ask("thread-9", "I want to talk to a human")
    turn = agent.ask("thread-9", "Ana Lopez, ana@example.com, my laptop screen flickers")

    assert "T-00001" in turn.answer and "ana@example.com" in turn.answer and "Ana" in turn.answer
    ticket = tickets.created[0]
    assert ticket["thread_id"] == "thread-9" and ticket["reason"] == "customer_request"
    assert ticket["email"] == "ana@example.com" and ticket["name"] == "Ana Lopez"
    assert ticket["transcript"][0] == {"role": "user", "content": "I want to talk to a human"}


def test_invented_contact_details_are_never_saved():
    agent, tickets = handoff_agent([
        Contact(name="Bob Smith", email="bob@invented.com", summary="help"),
    ])  # fmt: skip
    agent.ask("t", "get me a person, I'm at real@example.com")
    ticket = tickets.created[0]
    assert ticket["email"] == "real@example.com", "email must be one the customer typed"
    assert ticket["name"] is None, "name must appear in what the customer typed"


def test_second_handoff_points_to_the_existing_ticket():
    agent, tickets = handoff_agent([Contact(email="a@example.com", summary="x")] * 2)
    agent.ask("t", "human please, a@example.com")
    turn = agent.ask("t", "human please, a@example.com")
    assert turn.answer == TICKET_EXISTS.format(ref="T-00001") and len(tickets.created) == 1


def test_ticket_reason_records_a_failed_answer():
    agent, tickets = handoff_agent(
        [Contact(email="a@example.com", summary="x")],
        routes=[route("product_info"), route("handoff")],
        gate=False,
    )
    assert agent.ask("t", "When is the Nova X 2 out?").answer == NO_ANSWER_REPLY
    agent.ask("t", "yes please, a@example.com")
    assert tickets.created[0]["reason"] == "no_answer"


def test_ticket_reason_records_a_verification_lock():
    tickets, orders = Tickets(), Orders()
    # Only turns 1 and 4 reach the router: emails answering our question skip it
    spy = Spy([route("order"), route("handoff")])
    agent, _ = make_agent(
        spy, lookup_order=orders, save_ticket=tickets,
        extract_contact=lambda m: Contact(email="x@example.com", summary="locked out"),
    )  # fmt: skip
    for email in ("a@example.com", "b@example.com", "c@example.com"):
        agent.ask("t", f"VC-10003 {email}")
    agent.ask("t", "yes connect me, x@example.com")
    assert tickets.created[0]["reason"] == "verification_locked"


# ---------- catalog tools ----------


class ToolCallingFake(RecordingChat):
    """Returns scripted AIMessages (some with tool calls); records tool_choice used."""

    scripted: list = []
    tool_choices: list = []

    def bind_tools(self, tools, tool_choice=None, **kwargs):
        self.tool_choices.append(tool_choice)
        return self

    def invoke(self, messages, *args, **kwargs):
        self.seen.append(messages)
        return self.scripted.pop(0)


PRODUCT = {
    "sku": "AU-STRIDEOPEN", "name": "Stride Open", "category": "audio", "price_usd": 149.0,
    "rating": 4.4, "reviews": 812, "stock": "in stock", "description": "Open-ear headphones.",
}  # fmt: skip


def make_tool_agent(scripted, search=lambda **kw: [PRODUCT]):
    llm = ToolCallingFake(responses=["unused"])
    llm.scripted, llm.tool_choices = list(scripted), []
    tool = StructuredTool.from_function(search, name="search_products", description="search")
    spy = Spy([route("recommendation", "running headphones under 150")])
    agent, _ = make_agent(spy, answer_llm=llm, tools=[tool])
    return agent, llm


def call(name: str, args: dict, id_: str = "c1") -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": id_}])


def test_tool_results_become_numbered_citable_sources():
    calls = []

    def search(category: str | None = None, max_price: float | None = None):
        calls.append((category, max_price))
        return [PRODUCT]

    agent, llm = make_tool_agent(
        [call("search_products", {"category": "audio", "max_price": 150}),
         AIMessage("The Stride Open ($149) keeps your ears open [3].")],
        search=search,
    )  # fmt: skip
    turn = agent.ask("t", "running headphones under $150?")

    assert calls == [("audio", 150)]
    assert [c["n"] for c in turn.citations] == [3], "doc chunks are [1]-[2], the tool's is [3]"
    assert turn.citations[0]["source"] == "catalog:AU-STRIDEOPEN"
    tool_message = llm.seen[1][-1]
    assert tool_message.content.startswith("[3] Stride Open (SKU AU-STRIDEOPEN): $149.00, in stock")


def test_tool_errors_are_reported_to_the_model_not_raised():
    def broken(**kwargs):
        raise ValueError("bad category")

    agent, llm = make_tool_agent(
        [call("search_products", {}), AIMessage("Sorry, I couldn't search the catalog.")],
        search=broken,
    )
    turn = agent.ask("t", "headphones?")
    assert "Tool error" in llm.seen[1][-1].content and turn.answer.startswith("Sorry")


def test_tool_loop_stops_after_three_rounds():
    agent, llm = make_tool_agent(
        [call("search_products", {}, f"c{i}") for i in range(3)] + [AIMessage("Final [1].")]
    )
    turn = agent.ask("t", "headphones?")
    assert turn.answer == "Final [1]."
    assert llm.tool_choices[-1] == "none", "the last call forbids more tool use"


def test_order_details_are_json_in_the_prompt():
    agent, _, llm, _ = order_agent(1)
    agent.ask("t", "VC-10001 maya.patel@example.com")
    system = llm.seen[0][0].content
    details = json.loads(system.split("Order details:\n", 1)[1].split("\n\nPolicy sources:")[0])
    assert details["order_number"] == "VC-10001"


@pytest.mark.parametrize("message", ["VC-10003", "order 10003", "vc 10003"])
def test_order_number_formats(message):
    agent, _, _, _ = order_agent(1)
    assert agent.ask("t", message).answer == ASK_ORDER_EMAIL.format(order="VC-10003")


# ---------- fixes from the first real chats ----------


def test_policy_search_uses_the_question_not_the_email_reply():
    orders = Orders()
    spy = Spy([route("order", "track order VC-10003")])
    agent, _ = make_agent(spy, answers=["Shipped."], lookup_order=orders)
    agent.ask("t", "VC-10003")
    agent.ask("t", "maya.patel@example.com")  # wrong: question is kept for the retry
    turn = agent.ask("t", "sofia.ramirez@example.com")
    assert spy.searched == ["track order VC-10003"], "never search for an email address"
    assert turn.top_score == 0.9


class FailingThenWorking:
    """Fake chat model whose structured output fails (out of quota) or succeeds."""

    def __init__(self, fail: bool, result=None):
        self.fail, self.result, self.calls = fail, result, 0

    def with_structured_output(self, schema, method):
        from langchain_core.runnables import RunnableLambda

        def run(_):
            self.calls += 1
            if self.fail:
                raise RuntimeError("429 tokens per day")
            return self.result

        return RunnableLambda(run)


def test_router_falls_back_to_the_backup_model():
    from langchain_core.messages import HumanMessage

    from app.graph.agent import make_analyzer

    small = FailingThenWorking(fail=True)
    main = FailingThenWorking(fail=False, result=route("handoff"))
    result = make_analyzer(small, backup=main)([HumanMessage("I want a real person")])
    assert result.route == "handoff" and small.calls == 1 and main.calls == 1
