"""PII redaction: remove sensitive numbers from a message before anything else sees it.

Runs before the agent, so card numbers and SSNs never reach the LLM, the database (chat
memory), or Langfuse traces. Emails and order numbers are NOT redacted: the customer needs them
for order verification and support tickets.
"""

import re
from dataclasses import dataclass, field

# 13-19 digits, optionally grouped by spaces or dashes (card numbers)
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
SSN = re.compile(r"(?<!\d)\d{3}[- ]\d{2}[- ]\d{4}(?!\d)")
CVV = re.compile(r"\b(?:cvv|cvc|security code)\s*[:#]?\s*\d{3,4}\b", re.IGNORECASE)


@dataclass
class Redaction:
    text: str
    found: list[str] = field(default_factory=list)  # kinds removed, e.g. ["card", "ssn"]


def luhn_valid(digits: str) -> bool:
    """The checksum every real card number satisfies; filters out tracking numbers and the like."""
    total, double = 0, False
    for d in reversed(digits):
        n = int(d) * 2 if double else int(d)
        total += n - 9 if n > 9 else n
        double = not double
    return total % 10 == 0


def redact(text: str) -> Redaction:
    found: list[str] = []

    def card(match: re.Match) -> str:
        digits = re.sub(r"\D", "", match.group())
        if 13 <= len(digits) <= 19 and luhn_valid(digits):
            found.append("card")
            return "[CARD NUMBER REMOVED]"
        return match.group()

    def tag(kind: str, label: str):
        def replace(_: re.Match) -> str:
            found.append(kind)
            return label

        return replace

    text = SSN.sub(tag("ssn", "[SSN REMOVED]"), text)
    text = CVV.sub(tag("cvv", "[SECURITY CODE REMOVED]"), text)
    text = CARD.sub(card, text)
    return Redaction(text=text, found=sorted(set(found)))
