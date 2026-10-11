"""Human handoff: store a support ticket with the customer's contact details and the chat so far,
so the support team can pick it up in the admin inbox without asking again."""

from sqlalchemy.orm import Session

from app.db.models import Ticket


def create_ticket(
    session: Session,
    *,
    thread_id: str,
    email: str,
    summary: str,
    reason: str,
    name: str | None = None,
    transcript: list[dict] | None = None,
) -> str:
    """Returns the reference shown to the customer, e.g. T-00042."""
    ticket = Ticket(
        thread_id=thread_id,
        name=name,
        email=email.strip().lower(),
        summary=summary,
        reason=reason,
        transcript=transcript or [],
    )
    session.add(ticket)
    session.flush()  # assigns the id
    return ticket.reference
