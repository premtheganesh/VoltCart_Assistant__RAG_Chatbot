"""Verified order lookup. Security lives here, in code, never in the prompt:

- An order is returned only when the order number AND the email on it both match.
- "Wrong email" and "no such order" give the same answer, so nobody can probe which order
  numbers exist.
- The result holds only what the customer needs; never other customers' data.
- Attempt limits and per-conversation verification are enforced by the agent's order node.
"""

import re
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Customer, Order, OrderItem

# "VC-10003", "vc 10003", "VC10003", or bare digits right after "order" ("order #10017")
ORDER_NUMBER = re.compile(r"\bVC[-\s]?(\d{5})\b|\border\s*(?:number\s*)?#?\s*(\d{5})\b", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

STATUS_MEANING = {
    "processing": "Received and being prepared; can still be cancelled or the address changed.",
    "shipped": "With the carrier; can no longer be cancelled (refuse delivery or return instead).",
    "out_for_delivery": "With the local driver, arriving today.",
    "delivered": "Delivered to the address.",
    "cancelled": "Cancelled before shipping; refund or authorisation release in 3-5 business days.",
    "return_in_progress": "Return started; waiting for the item to arrive.",
    "refunded": "Return inspected and refund issued.",
}


def find_order_numbers(text: str) -> list[str]:
    """'VC-10003', 'vc10003', 'order 10017' -> canonical VC-xxxxx numbers, in order of mention."""
    seen: dict[str, None] = {}
    for prefixed, bare in ORDER_NUMBER.findall(text):
        seen.setdefault(f"VC-{prefixed or bare}")
    return list(seen)


def find_emails(text: str) -> list[str]:
    return [e.lower().rstrip(".") for e in EMAIL.findall(text)]


def _money(value: Decimal) -> str:
    return f"${value:,.2f}"


def verify_order(session: Session, order_number: str, email: str) -> dict | None:
    """The order as the customer may see it, or None if the number and email don't match."""
    order = session.scalar(
        select(Order)
        .join(Customer)
        .where(
            Order.order_number == order_number.upper(),
            Customer.email == email.strip().lower(),  # emails are stored lowercase
        )
        .options(selectinload(Order.items).selectinload(OrderItem.product))
        .options(selectinload(Order.shipment))
    )
    if order is None:
        return None
    shipment = order.shipment
    return {
        "order_number": order.order_number,
        "status": order.status,
        "status_meaning": STATUS_MEANING[order.status],
        "placed_on": order.placed_at.date().isoformat(),
        "shipping_method": order.shipping_method,
        "ship_to": f"{order.shipping_city}, {order.shipping_state}",
        "items": [
            {"name": i.product.name, "quantity": i.quantity, "unit_price": _money(i.unit_price_usd)}
            for i in order.items
        ],
        "subtotal": _money(order.subtotal_usd),
        "shipping": _money(order.shipping_usd),
        "tax": _money(order.tax_usd),
        "total": _money(order.total_usd),
        "shipment": None
        if shipment is None
        else {
            "carrier": shipment.carrier,
            "tracking_number": shipment.tracking_number,
            "shipped_on": shipment.shipped_at.date().isoformat(),
            "estimated_delivery": shipment.estimated_delivery.isoformat(),
            "delivered_on": shipment.delivered_at.date().isoformat()
            if shipment.delivered_at
            else None,
        },
    }
