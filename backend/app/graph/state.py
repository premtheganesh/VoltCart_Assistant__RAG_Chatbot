"""What the agent remembers. LangGraph saves this after every step (the checkpointer), keyed by
the conversation's thread id, so the next message continues where the last one left off.

Everything stored must be plain data (str, dict, list): it is serialized to Postgres.
"""

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

Route = Literal["product_info", "recommendation", "order", "handoff", "smalltalk", "off_topic"]


class Analysis(BaseModel):
    """The router's output: which path to take, and what to search for."""

    route: Route = Field(description="Which kind of request this is")
    search_query: str = Field(
        description="The message rewritten as a standalone search query: pronouns like 'it' "
        "replaced with what they refer to from the conversation, product names exact"
    )


class Contact(BaseModel):
    """Contact details for a support ticket, extracted from the chat."""

    name: str | None = Field(default=None, description="The customer's name, if given")
    email: str | None = Field(default=None, description="The customer's email, if given")
    summary: str = Field(description="One or two sentences on what the customer needs")


Awaiting = Literal["order_email", "handoff_contact"]


class ChatState(TypedDict, total=False):
    # Full conversation; add_messages appends new messages instead of replacing the list
    messages: Annotated[list[AnyMessage], add_messages]
    # Per-turn working data (reset by the router each turn)
    route: Route
    search_query: str
    sources: list[dict]  # retrieved chunks, numbered [1]..[n] in the prompt
    top_score: float | None
    passed_gate: bool | None
    citations: list[dict]  # the sources the answer actually cited
    safety: str  # input check verdict: safe / prompt_attack / harmful / abuse
    safety_reason: str
    grounded: bool | None  # L2 check result (None when the check is off or not applicable)

    # Kept across turns (the conversation's security and handoff memory)
    verified_orders: dict[str, str]  # order number -> email it was verified with
    verify_attempts: int  # failed order verifications in this conversation
    pending_order: str | None  # order number waiting for its email
    pending_question: str | None  # what was asked about that order, for the policy search
    awaiting: Awaiting | None  # what the bot just asked the customer for
    handoff_reason: str | None  # why a human is needed, for the ticket
    ticket_ref: str | None  # ticket already created in this conversation
