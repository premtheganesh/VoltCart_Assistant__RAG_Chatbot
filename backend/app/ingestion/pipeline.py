"""Incremental ingestion: files + catalog -> parsed -> chunked -> embedded -> stored.

Re-running is cheap and safe:
- a source whose content hash and embedding model are unchanged is skipped entirely;
- a changed source is re-chunked, but chunks whose exact text was embedded before reuse
  their stored vector (only new or edited chunks cost an API call);
- a source that disappeared is deleted with its chunks.
The caller owns the transaction: nothing is written unless every embedding call succeeded.
"""

import hashlib
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.embeddings import Embeddings
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import EMBED_DIM, Chunk, Document, Product
from app.ingestion.chunking import TextChunk, chunk_document
from app.ingestion.loaders import LOADERS, Block, ParsedDocument, load_file

log = logging.getLogger(__name__)

CATALOG_PREFIX = "catalog:"


def sha256(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


# ---------- product tagging ----------

# Trailing words customers often leave out: "Pulse ANC" for "Pulse ANC Headphones"
SHORT_NAME = re.compile(r" (Headphones|Earbuds|Smart Speaker|Smart Plug|Video Doorbell|Color|"
                        r"Laptop Sleeve|65W GaN Charger)$")  # fmt: skip


class ProductTagger:
    """Finds which catalog products a piece of text mentions.

    Longest names match first and are masked, so "Nova X Pro" never also counts as "Nova X".
    """

    def __init__(self, products: Iterable[tuple[str, str]]):  # (sku, name)
        aliases: dict[str, str] = {}
        for sku, name in products:
            base = name.split(" (")[0]
            for alias in {sku, base, SHORT_NAME.sub("", base)}:
                aliases.setdefault(alias, sku)
        self._patterns = [
            (re.compile(rf"(?<![\w-]){re.escape(alias)}(?![\w-])"), sku)
            for alias, sku in sorted(aliases.items(), key=lambda a: -len(a[0]))
        ]

    def tag(self, text: str) -> list[str]:
        found: set[str] = set()
        for pattern, sku in self._patterns:
            text, hits = pattern.subn(" ", text)
            if hits:
                found.add(sku)
        return sorted(found)


# ---------- catalog products as documents ----------


def product_document(product: Product) -> ParsedDocument:
    """One product = one small document, so "earbuds for running" can find products by meaning.

    Stock is left out on purpose: it changes constantly and is looked up live by a tool.
    """
    specs = "\n".join(
        f"- {key.replace('_', ' ').capitalize()}: {value}" for key, value in product.specs.items()
    )
    text = (
        f"{product.name} (SKU {product.sku})\n"
        f"Category: {product.category.replace('_', ' ')}. Price: ${product.price_usd:,.2f}. "
        f"Rating: {product.rating}/5 from {product.review_count} reviews. "
        f"Colors: {', '.join(product.colors)}.\n"
        f"{product.short_description}\n"
        f"Tags: {', '.join(product.tags)}\n"
        f"Specifications:\n{specs}"
    )
    return ParsedDocument(
        source=f"{CATALOG_PREFIX}{product.sku}",
        title=product.name,
        doc_type="product",
        blocks=[Block("text", text)],
        products=[product.sku],
    )


# ---------- pipeline ----------


@dataclass
class IngestReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    chunks_written: int = 0
    chunks_embedded: int = 0
    chunks_reused: int = 0
    embed_calls: int = 0

    def summary(self) -> str:
        return (
            f"documents: {len(self.added)} added, {len(self.updated)} updated, "
            f"{len(self.unchanged)} unchanged, {len(self.deleted)} deleted\n"
            f"chunks: {self.chunks_written} written "
            f"({self.chunks_embedded} newly embedded, {self.chunks_reused} reused); "
            f"embedding API calls: {self.embed_calls}"
        )


@dataclass
class _Pending:
    parsed: ParsedDocument
    content_hash: str
    chunks: list[TextChunk]
    chunk_hashes: list[str]
    products: list[list[str]]
    existing: Document | None


def _discover_files(docs_dir: Path, source_root: Path) -> dict[str, Path]:
    return {
        p.relative_to(source_root).as_posix(): p
        for p in sorted(docs_dir.rglob("*"))
        if p.is_file() and p.suffix.lower() in LOADERS
    }


def ingest(
    session: Session,
    embedder: Embeddings,
    embed_model: str,
    docs_dir: Path,
    *,
    source_root: Path,
    include_catalog: bool = True,
    force: bool = False,
    max_tokens: int = 600,
    overlap_tokens: int = 80,
    batch_size: int = 96,
) -> IngestReport:
    report = IngestReport()
    products = list(session.scalars(select(Product).order_by(Product.sku)))
    tagger = ProductTagger((p.sku, p.name) for p in products)

    # Every candidate source: (source, content hash, how to parse it)
    candidates: list[tuple[str, str, object]] = []
    for source, path in _discover_files(docs_dir, source_root).items():
        candidates.append((source, sha256(path.read_bytes()), path))
    if include_catalog:
        for product in products:
            doc = product_document(product)
            candidates.append((doc.source, sha256(doc.blocks[0].text), doc))

    # Only sources inside this run's scope can be deleted
    dir_prefix = docs_dir.relative_to(source_root).as_posix().rstrip("/") + "/"
    existing = {
        d.source: d
        for d in session.scalars(select(Document))
        if d.source.startswith(dir_prefix)
        or (include_catalog and d.source.startswith(CATALOG_PREFIX))
    }

    pending: list[_Pending] = []
    for source, content_hash, origin in candidates:
        old = existing.get(source)
        if (
            old
            and not force
            and old.content_hash == content_hash
            and old.embed_model == embed_model
        ):
            report.unchanged.append(source)
            continue
        parsed = origin if isinstance(origin, ParsedDocument) else load_file(origin, source)
        chunks = chunk_document(parsed, max_tokens, overlap_tokens)
        pending.append(
            _Pending(
                parsed=parsed,
                content_hash=content_hash,
                chunks=chunks,
                chunk_hashes=[sha256(f"{embed_model}\n{c.embed_text}") for c in chunks],
                # A catalog entry is about its own product only (its specs may name others).
                # File chunks: products the text names; if none, the document's products.
                products=[
                    parsed.products
                    if parsed.doc_type == "product"
                    else tagger.tag(c.embed_text) or parsed.products
                    for c in chunks
                ],
                existing=old,
            )
        )
        (report.updated if old else report.added).append(source)

    # Reuse vectors for chunk texts embedded before (by any document), embed only the rest
    vectors: dict[str, list[float]] = {}
    needed = {h for p in pending for h in p.chunk_hashes}
    if needed and not force:
        rows = session.execute(
            select(Chunk.chunk_hash, Chunk.embedding).where(
                Chunk.chunk_hash.in_(needed), Chunk.embed_model == embed_model
            )
        )
        vectors = {h: list(e) for h, e in rows}
    to_embed: dict[str, str] = {}
    for p in pending:
        for h, c in zip(p.chunk_hashes, p.chunks, strict=True):
            if h not in vectors:
                to_embed.setdefault(h, c.embed_text)

    hashes, texts = list(to_embed), list(to_embed.values())
    for start in range(0, len(texts), batch_size):
        batch = embedder.embed_documents(texts[start : start + batch_size])
        report.embed_calls += 1
        for h, vector in zip(hashes[start : start + batch_size], batch, strict=True):
            if len(vector) != EMBED_DIM:
                raise ValueError(
                    f"{embed_model} returned {len(vector)}-dimensional vectors, but the "
                    f"chunks.embedding column holds {EMBED_DIM}. Change EMBED_DIM with a "
                    "migration, then re-ingest with --force."
                )
            vectors[h] = vector
        log.info("embedded %d/%d chunks", min(start + batch_size, len(texts)), len(texts))
    report.chunks_embedded = len(to_embed)

    # Write: replace each pending document's chunks
    for p in pending:
        doc = p.existing or Document(source=p.parsed.source)
        if doc.id is not None:
            session.execute(delete(Chunk).where(Chunk.document_id == doc.id))
            session.expire(doc, ["chunks"])
        doc.title, doc.doc_type = p.parsed.title, p.parsed.doc_type
        doc.url, doc.updated = p.parsed.url, p.parsed.updated
        doc.content_hash, doc.embed_model = p.content_hash, embed_model
        session.add(doc)
        session.flush()
        session.add_all(
            Chunk(
                document_id=doc.id,
                chunk_index=c.index,
                heading=c.heading,
                content=c.content,
                token_count=c.token_count,
                page=c.page,
                products=tags,
                chunk_hash=h,
                embedding=vectors[h],
                embed_model=embed_model,
            )
            for c, h, tags in zip(p.chunks, p.chunk_hashes, p.products, strict=True)
        )
        report.chunks_written += len(p.chunks)
    report.chunks_reused = report.chunks_written - report.chunks_embedded

    # Delete sources that no longer exist
    seen = {source for source, _, _ in candidates}
    gone = [d for source, d in existing.items() if source not in seen]
    if gone:
        session.execute(delete(Document).where(Document.id.in_([d.id for d in gone])))
        report.deleted = sorted(d.source for d in gone)
    session.flush()
    return report
