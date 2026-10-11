"""Product tools: exact, live catalog data (price, stock, specs) straight from the database.

Documents explain and recommend; these answer what documents can't: "under $150", "in stock",
"compare these two". Predefined queries only; the LLM picks arguments, never writes SQL.
"""

from typing import Literal

from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session

from app.db.models import Product

Category = Literal["laptops", "audio", "phones", "smart_home", "accessories"]
Sort = Literal["price_low", "price_high", "rating"]
LOW_STOCK = 10


def stock_label(stock: int) -> str:
    if stock == 0:
        return "out of stock"
    return f"low stock ({stock} left)" if stock < LOW_STOCK else "in stock"


def summary(p: Product) -> dict:
    return {
        "sku": p.sku,
        "name": p.name,
        "category": p.category,
        "price_usd": float(p.price_usd),
        "rating": float(p.rating),
        "reviews": p.review_count,
        "stock": stock_label(p.stock),
        "description": p.short_description,
    }


def details(p: Product) -> dict:
    return {**summary(p), "colors": p.colors, "tags": p.tags, "specs": p.specs}


def search_products(
    session: Session,
    *,
    category: Category | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    keywords: str | None = None,
    in_stock_only: bool = False,
    sort: Sort = "rating",
    limit: int = 5,
) -> list[dict]:
    """Every keyword must appear in the name, description, tags or specs (case-insensitive)."""
    stmt = select(Product)
    if category:
        stmt = stmt.where(Product.category == category)
    if min_price is not None:
        stmt = stmt.where(Product.price_usd >= min_price)
    if max_price is not None:
        stmt = stmt.where(Product.price_usd <= max_price)
    if in_stock_only:
        stmt = stmt.where(Product.stock > 0)
    searchable = func.concat_ws(
        " ", Product.name, Product.short_description,
        func.array_to_string(Product.tags, " "), cast(Product.specs, String),
    )  # fmt: skip
    for word in (keywords or "").split():
        stmt = stmt.where(searchable.ilike(f"%{word}%"))
    order = {
        "price_low": [Product.price_usd.asc()],
        "price_high": [Product.price_usd.desc()],
        "rating": [Product.rating.desc(), Product.review_count.desc()],
    }[sort]
    stmt = stmt.order_by(*order, Product.sku).limit(max(1, min(limit, 10)))
    return [summary(p) for p in session.scalars(stmt)]


def find_product(session: Session, name_or_sku: str) -> Product | None:
    """Exact SKU, exact name, then the closest name match ("pulse anc" -> Pulse ANC Headphones)."""
    text = name_or_sku.strip()
    if p := session.scalar(select(Product).where(func.upper(Product.sku) == text.upper())):
        return p
    if p := session.scalar(select(Product).where(func.lower(Product.name) == text.lower())):
        return p
    words = text.split()
    if not words:
        return None
    matches = session.scalars(
        select(Product)
        .where(*(Product.name.ilike(f"%{w}%") for w in words))
        .order_by(func.length(Product.name))  # "Nova X" before "Nova X Pro"
    ).all()
    return matches[0] if matches else None


def get_product(session: Session, name_or_sku: str) -> dict | None:
    p = find_product(session, name_or_sku)
    return details(p) if p else None


def compare_products(session: Session, names_or_skus: list[str]) -> list[dict]:
    """Full details for 2 to 4 products, in the order asked. Unknown names are skipped."""
    found: list[dict] = []
    for name in names_or_skus[:4]:
        p = find_product(session, name)
        if p and all(f["sku"] != p.sku for f in found):
            found.append(details(p))
    return found
