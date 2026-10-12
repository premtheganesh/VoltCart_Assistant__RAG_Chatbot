"""Grounding check (L2, toggle GROUNDING_CHECK): a judge model lists the answer's claims that its
sources don't support. The agent then rewrites the answer once; if it is still unsupported, the
customer gets an honest "I'm not sure" with an offer of human help instead of a guess.

L1 (always on) is the relevance gate + "answer only from the sources" prompt + citations.
"""

import logging
from collections.abc import Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

GROUNDING_PROMPT = """You check a customer-support answer against the sources it was written \
from. List every claim in the answer (facts about products, prices, specs, policies, steps, \
dates, orders) that the sources do not state or directly imply. Greetings, offers to help, and \
questions back to the customer are not claims. Rewording, summarising and simple arithmetic on \
source facts are supported. supported is true only if the list is empty."""


class Grounding(BaseModel):
    supported: bool
    unsupported_claims: list[str] = Field(default_factory=list)


GroundingChecker = Callable[[str, str], Grounding]  # (answer, sources text) -> verdict


def make_grounding_checker(llm: BaseChatModel) -> GroundingChecker:
    judge = llm.with_structured_output(Grounding, method="json_schema")

    def check(answer: str, sources: str) -> Grounding:
        try:
            return judge.invoke(
                [
                    SystemMessage(GROUNDING_PROMPT),
                    HumanMessage(f"Sources:\n{sources}\n\nAnswer:\n{answer}"),
                ]
            )
        except Exception as exc:  # a judge outage must not block answers (L1 still applies)
            log.warning("grounding check unavailable: %s", str(exc)[:120])
            return Grounding(supported=True)

    return check
