"""Load sample_data/data/*.json into Postgres. Safe to re-run: replaces all store data.

Run: make seed   (after: make migrate)
"""

import json
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT
from app.db.models import Customer, Order, OrderItem, Product, Shipment
from app.db.session import get_engine

DATA_DIR = PROJECT_ROOT / "sample_data" / "data"
STORE_TABLES = ["shipments", "order_items", "orders", "customers", "products"]


def load(name: str) -> list[dict]:
    return json.loads((DATA_DIR / name).read_text())


def seed(session: Session) -> dict[str, int]:
    session.execute(text(f"TRUNCATE {', '.join(STORE_TABLES)} RESTART IDENTITY CASCADE"))

    products = {
        p["sku"]: Product(
            sku=p["sku"],
            name=p["name"],
            category=p["category"],
            price_usd=Decimal(str(p["price_usd"])),
            stock=p["stock"],
            rating=Decimal(str(p["rating"])),
            review_count=p["review_count"],
            short_description=p["short_description"],
            tags=p["tags"],
            colors=p["colors"],
            specs=p["specs"],
        )
        for p in load("catalog.json")
    }
    customers = {
        c["email"].lower(): Customer(**{**c, "email": c["email"].lower()})
        for c in load("customers.json")
    }
    session.add_all([*products.values(), *customers.values()])

    orders = load("orders.json")
    for o in orders:
        order = Order(
            order_number=o["order_number"],
            customer=customers[o["customer_email"].lower()],
            status=o["status"],
            placed_at=datetime.fromisoformat(o["placed_at"]),
            shipping_method=o["shipping_method"],
            shipping_city=o["shipping_city"],
            shipping_state=o["shipping_state"],
            subtotal_usd=Decimal(o["subtotal_usd"]),
            shipping_usd=Decimal(o["shipping_usd"]),
            tax_usd=Decimal(o["tax_usd"]),
            total_usd=Decimal(o["total_usd"]),
            items=[
                OrderItem(
                    product=products[i["sku"]],
                    quantity=i["quantity"],
                    unit_price_usd=Decimal(i["unit_price_usd"]),
                )
                for i in o["items"]
            ],
        )
        if s := o["shipment"]:
            order.shipment = Shipment(
                carrier=s["carrier"],
                tracking_number=s["tracking_number"],
                shipped_at=datetime.fromisoformat(s["shipped_at"]),
                estimated_delivery=date.fromisoformat(s["estimated_delivery"]),
                delivered_at=datetime.fromisoformat(s["delivered_at"])
                if s["delivered_at"]
                else None,
            )
        session.add(order)

    session.flush()
    return {
        table: session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
        for table in reversed(STORE_TABLES)
    }


def main() -> None:
    with Session(get_engine()) as session, session.begin():
        counts = seed(session)
    for table, count in counts.items():
        print(f"  {table:<12} {count:>4} rows")
    print("Seed complete.")


if __name__ == "__main__":
    main()
