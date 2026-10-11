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
