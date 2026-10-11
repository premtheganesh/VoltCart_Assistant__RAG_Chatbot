"""Generate sample_data/data/orders.json deterministically (fixed seed) from catalog + customers.

Shipping costs, delivery times and statuses follow sample_data/source/FACTS.md.
Run: make generate-orders
"""

import json
import random
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.config import PROJECT_ROOT

DATA_DIR = PROJECT_ROOT / "sample_data" / "data"
TODAY = datetime(2026, 10, 10, 15, 0, tzinfo=UTC)
SEED = 42

# Simplified combined sales-tax rates by delivery state
TAX_RATES = {
    "TX": "0.0825",
    "MA": "0.0625",
    "AZ": "0.0840",
    "WA": "0.1025",
    "GA": "0.0740",
    "CO": "0.0780",
    "IL": "0.1025",
    "HI": "0.0450",
    "CA": "0.0938",
    "OH": "0.0800",
    "FL": "0.0700",
    "AK": "0.0000",
}
REMOTE_STATES = {"AK", "HI"}

# (status, how many orders, range of days ago the order was placed)
STATUS_PLAN = [
    ("processing", 4, (0, 1)),
    ("out_for_delivery", 2, (2, 3)),
    ("shipped", 5, (2, 5)),
    ("delivered", 13, (8, 70)),
    ("cancelled", 2, (10, 40)),
    ("return_in_progress", 2, (14, 25)),
    ("refunded", 2, (35, 60)),
]
CARRIERS = {"UPS": "1Z{:016d}", "FedEx": "{:012d}", "USPS": "9400{:018d}"}
TRANSIT_DAYS = {"standard": 4, "express": 2, "next_day": 1}


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def shipping_cost(method: str, subtotal: Decimal, state: str) -> Decimal:
    if state in REMOTE_STATES:
        return Decimal("12.99")
    if method == "express":
        return Decimal("14.99")
    if method == "next_day":
        return Decimal("24.99")
    return Decimal("0.00") if subtotal >= 35 else Decimal("5.99")


def add_business_days(start: datetime, days: int) -> datetime:
    current = start
    while days > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days -= 1
    return current


def build_orders() -> list[dict]:
    rng = random.Random(SEED)
    products = json.loads((DATA_DIR / "catalog.json").read_text())
    customers = json.loads((DATA_DIR / "customers.json").read_text())

    statuses = [(s, days) for s, count, days in STATUS_PLAN for _ in range(count)]
    rng.shuffle(statuses)

    orders = []
    for index, (status, (min_days, max_days)) in enumerate(statuses):
        customer = customers[index % len(customers)] if index < 24 else rng.choice(customers)
        state = customer["state"]
        placed_at = TODAY - timedelta(days=rng.randint(min_days, max_days), hours=rng.randint(0, 9))

        picks = rng.sample(products, k=rng.choice([1, 1, 1, 2, 2, 3]))
        items = [
            {
                "sku": p["sku"],
                "quantity": 1 if p["price_usd"] > 100 else rng.choice([1, 2]),
                "unit_price_usd": f"{p['price_usd']:.2f}",
            }
            for p in picks
        ]
        subtotal = money(sum(Decimal(i["unit_price_usd"]) * i["quantity"] for i in items))

        if state in REMOTE_STATES:
            method = "standard"
        elif status == "out_for_delivery":
            method = rng.choice(["express", "next_day"])
        else:
            method = rng.choices(["standard", "express", "next_day"], weights=[7, 2, 1])[0]
        ship = shipping_cost(method, subtotal, state)
        tax = money(subtotal * Decimal(TAX_RATES[state]))

        order = {
            "order_number": f"VC-{10001 + index}",
            "customer_email": customer["email"],
            "status": status,
            "placed_at": placed_at.isoformat(),
            "shipping_method": method,
            "shipping_city": customer["city"],
            "shipping_state": state,
            "items": items,
            "subtotal_usd": str(subtotal),
            "shipping_usd": str(ship),
            "tax_usd": str(tax),
            "total_usd": str(money(subtotal + ship + tax)),
            "shipment": None,
        }

        if status not in ("processing", "cancelled"):
            shipped_at = add_business_days(placed_at, 1)
            transit = TRANSIT_DAYS[method] + (3 if state in REMOTE_STATES else 0)
            eta = add_business_days(shipped_at, transit)
            carrier = rng.choice(list(CARRIERS))
            delivered = status in ("delivered", "return_in_progress", "refunded")
            order["shipment"] = {
                "carrier": carrier,
                "tracking_number": CARRIERS[carrier].format(rng.randrange(10**11, 10**12)),
                "shipped_at": shipped_at.isoformat(),
                "estimated_delivery": eta.date().isoformat(),
                "delivered_at": eta.replace(hour=18).isoformat() if delivered else None,
            }
        orders.append(order)

    return sorted(orders, key=lambda o: o["order_number"])


def main() -> None:
    orders = build_orders()
    path = DATA_DIR / "orders.json"
    path.write_text(json.dumps(orders, indent=2) + "\n")
    print(f"Wrote {len(orders)} orders to {path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
