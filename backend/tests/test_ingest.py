"""Ingestion pipeline: product tagging, embedder factory, and incremental indexing.

Integration tests run inside a transaction that is rolled back, so the real database is never
changed, and they use a fake embedder, so they make no API calls.
"""

import json
import math
import shutil
from decimal import Decimal

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding, Embeddings
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT, Settings
from app.db.models import EMBED_DIM, Chunk, Document, Product
from app.db.session import get_engine
from app.ingestion.pipeline import ProductTagger, ingest, product_document
from app.llm.embeddings import embed_model_id, get_embedder

DOCS = PROJECT_ROOT / "sample_data" / "docs"
CATALOG = json.loads((PROJECT_ROOT / "sample_data/data/catalog.json").read_text())
TAGGER = ProductTagger((p["sku"], p["name"]) for p in CATALOG)


# ---------- product tagging (unit) ----------


@pytest.mark.parametrize(
    ("text", "skus"),
    [
        ("The Nova X Pro has a 10x zoom.", ["PH-NOVAXPRO"]),
        ("Compare the Nova X and the Nova X Pro.", ["PH-NOVAX", "PH-NOVAXPRO"]),
        ("The HomeHub Mini has no Zigbee radio.", ["SH-HOMEHUBMINI"]),
        ("Pair it with the HomeHub.", ["SH-HOMEHUB"]),
        ("The Pulse ANC folds flat.", ["AU-PULSEANC"]),
        ("Pulse Buds Pro charge on Qi pads.", ["AU-PULSEBUDS"]),
        ("VoltBook Pro 14 vs VoltBook Pro 16", ["VB-PRO14", "VB-PRO16"]),
        ("Order VB-AIR14 today", ["VB-AIR14"]),
        ("The GlowBulb Color (2-pack) and GlowPlug", ["SH-GLOWBULB", "SH-GLOWPLUG"]),
        ("Novas and VoltBooks in general", []),
    ],
)
def test_product_tagger(text, skus):
    assert TAGGER.tag(text) == skus


def test_product_document_has_facts_but_not_stock():
    product = Product(
        sku="VB-PRO16", name="VoltBook Pro 16", category="laptops", price_usd=Decimal("1799"),
        stock=15, rating=Decimal("4.8"), review_count=10, short_description="Creator laptop.",
        tags=["video"], colors=["Space Gray"], specs={"memory": "32 GB", "water_resistance": "No"},
    )  # fmt: skip
    doc = product_document(product)
    body = doc.blocks[0].text

    assert doc.source == "catalog:VB-PRO16" and doc.doc_type == "product"
    assert doc.products == ["VB-PRO16"]
    assert "$1,799.00" in body and "- Memory: 32 GB" in body and "- Water resistance: No" in body
    assert "stock" not in body.lower()


# ---------- embedder factory (unit) ----------


def test_fake_embedder_matches_column_size():
    settings = Settings(_env_file=None, embed_provider="fake")
    assert len(get_embedder(settings).embed_query("hello")) == EMBED_DIM
    assert embed_model_id(settings) == "fake:embed-multilingual-v3.0"


def test_cohere_without_key_fails_clearly():
    with pytest.raises(RuntimeError, match="COHERE_API_KEY"):
        get_embedder(Settings(_env_file=None, embed_provider="cohere", cohere_api_key=None))


def test_unknown_provider_fails_clearly():
    with pytest.raises(ValueError, match="EMBED_PROVIDER"):
        get_embedder(Settings(_env_file=None, embed_provider="nope"))


# ---------- pipeline (integration) ----------


class CountingEmbedder(Embeddings):
    def __init__(self, size: int = EMBED_DIM, fail_on_call: int | None = None):
        self.inner = DeterministicFakeEmbedding(size=size)
        self.calls, self.texts = 0, 0
        self.fail_on_call = fail_on_call

    def embed_documents(self, texts):
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise ConnectionError("embedding API down")
        self.texts += len(texts)
        return self.inner.embed_documents(texts)

    def embed_query(self, text):
        return self.inner.embed_query(text)


@pytest.fixture
def session():
    with get_engine().connect() as conn:
        trans = conn.begin()
        s = Session(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield s
        finally:
            s.close()
            trans.rollback()


@pytest.fixture
def kb(tmp_path):
    """A temporary knowledge base folder with two real documents."""
    docs = tmp_path / "docs"
    docs.mkdir()
    for name in ("shipping-policy.html", "stride-sport-earbuds-manual.pdf"):
        shutil.copy(DOCS / name, docs / name)
    return docs


def run(session, docs, embedder=None, model="fake:test", **kw):
    embedder = embedder or CountingEmbedder()
    report = ingest(session, embedder, model, docs, source_root=docs.parent,
                    include_catalog=kw.pop("include_catalog", False), **kw)  # fmt: skip
    return report, embedder


def chunks_of(session, source):
    return list(
        session.scalars(
            select(Chunk)
            .join(Document)
            .where(Document.source == source)
            .order_by(Chunk.chunk_index)
        )
    )


@pytest.mark.integration
def test_first_run_embeds_and_stores_everything(session, kb):
    report, emb = run(session, kb, batch_size=10)

    assert sorted(report.added) == [
        "docs/shipping-policy.html",
        "docs/stride-sport-earbuds-manual.pdf",
    ]
    assert report.chunks_written == report.chunks_embedded == emb.texts > 0
    assert emb.calls == math.ceil(emb.texts / 10), "chunks are embedded in batches"

    stride = chunks_of(session, "docs/stride-sport-earbuds-manual.pdf")
    assert all(len(c.embedding) == EMBED_DIM and c.embed_model == "fake:test" for c in stride)
    assert all(c.heading.startswith("Stride Sport Earbuds Manual") for c in stride)
    assert all("AU-STRIDE" in c.products for c in stride), "manual chunks inherit the product"
    assert stride[0].page == 1
    doc = session.scalar(select(Document).where(Document.source == "docs/shipping-policy.html"))
    assert (doc.doc_type, doc.url) == (
        "help_center",
        "https://voltcart.example/help/shipping-policy",
    )


@pytest.mark.integration
def test_rerun_without_changes_does_nothing(session, kb):
    run(session, kb)
    report, emb = run(session, kb)

    assert len(report.unchanged) == 2 and not (report.added or report.updated or report.deleted)
    assert emb.calls == 0 and report.chunks_written == 0


@pytest.mark.integration
def test_editing_a_file_reembeds_only_the_changed_chunk(session, kb):
    first, _ = run(session, kb)
    page = kb / "shipping-policy.html"
    page.write_text(page.read_text().replace("Reno, NV", "Sparks, NV"))

    report, emb = run(session, kb)

    assert report.updated == ["docs/shipping-policy.html"]
    assert report.unchanged == ["docs/stride-sport-earbuds-manual.pdf"]
    assert emb.texts == 1, "only the edited chunk costs an embedding call"
    assert report.chunks_reused == report.chunks_written - 1
    contents = " ".join(c.content for c in chunks_of(session, "docs/shipping-policy.html"))
    assert "Sparks, NV" in contents and "Reno, NV" not in contents


@pytest.mark.integration
def test_new_policy_version_replaces_the_old_one(session, kb):
    """The v2 returns page (45 days) must fully replace v1 (30 days): no stale chunks left."""
    returns = kb / "returns-and-refunds.html"
    shutil.copy(DOCS / "returns-and-refunds.html", returns)
    run(session, kb)
    old = " ".join(c.content for c in chunks_of(session, "docs/returns-and-refunds.html"))
    assert "30 days" in old and "45 days" not in old

    shutil.copy(PROJECT_ROOT / "sample_data/test_only/returns-and-refunds.html", returns)
    report, _ = run(session, kb)

    assert report.updated == ["docs/returns-and-refunds.html"]
    new = " ".join(c.content for c in chunks_of(session, "docs/returns-and-refunds.html"))
    assert "45 days" in new and "30 days" not in new


@pytest.mark.integration
def test_deleted_file_is_removed_with_its_chunks(session, kb):
    run(session, kb)
    (kb / "stride-sport-earbuds-manual.pdf").unlink()

    report, _ = run(session, kb)

    assert report.deleted == ["docs/stride-sport-earbuds-manual.pdf"]
    assert chunks_of(session, "docs/stride-sport-earbuds-manual.pdf") == []
    assert chunks_of(session, "docs/shipping-policy.html")


@pytest.mark.integration
def test_force_and_model_change_reembed_everything(session, kb):
    first, _ = run(session, kb)

    forced, emb = run(session, kb, force=True)
    assert len(forced.updated) == 2 and emb.texts == first.chunks_written

    switched, emb = run(session, kb, model="fake:other-model")
    assert len(switched.updated) == 2 and emb.texts == first.chunks_written, (
        "vectors from different models must never be mixed"
    )


@pytest.mark.integration
def test_embedding_failure_writes_nothing(session, kb):
    with pytest.raises(ConnectionError):
        run(session, kb, embedder=CountingEmbedder(fail_on_call=2), batch_size=5)
    assert session.scalar(select(func.count()).select_from(Document).where(
        Document.source.like("docs/%"))) == 0  # fmt: skip


@pytest.mark.integration
def test_wrong_vector_size_fails_with_a_clear_message(session, kb):
    with pytest.raises(ValueError, match="1024"):
        run(session, kb, embedder=CountingEmbedder(size=8))


@pytest.mark.integration
def test_vector_and_keyword_search_work(session, kb):
    shutil.copy(DOCS / "returns-and-refunds.html", kb / "returns-and-refunds.html")
    run(session, kb)
    target = chunks_of(session, "docs/returns-and-refunds.html")[3]

    nearest = session.scalar(
        select(Chunk.id)
        .join(Document)
        .where(Document.source.like("docs/%"))
        .order_by(Chunk.embedding.cosine_distance(target.embedding))
        .limit(1)
    )
    assert nearest == target.id, "a chunk's own vector is its nearest neighbour"

    hits = (
        session.execute(
            text(
                "SELECT c.heading FROM chunks c JOIN documents d ON d.id = c.document_id "
                "WHERE d.source LIKE 'docs/%' "
                "AND c.tsv @@ plainto_tsquery('english', 'restocking fee')"
            )
        )
        .scalars()
        .all()
    )
    assert "Returns and Refunds > Is there a restocking fee?" in hits


@pytest.mark.integration
def test_catalog_products_become_documents(session, kb):
    if session.scalar(select(func.count()).select_from(Product)) == 0:
        pytest.skip("run make seed first")
    run(session, kb, include_catalog=True)

    products = session.scalars(
        select(Document).where(Document.source.like("catalog:%")).order_by(Document.source)
    ).all()
    assert len(products) == len(CATALOG)
    for doc in products:
        chunks = chunks_of(session, doc.source)
        assert len(chunks) == 1 and chunks[0].products == [doc.source.removeprefix("catalog:")]
        assert doc.doc_type == "product"


def test_cohere_client_receives_the_real_key_not_the_masked_one():
    """Regression: passing a SecretStr made langchain-cohere send '**********' (HTTP 401)."""
    settings = Settings(_env_file=None, embed_provider="cohere", cohere_api_key="test-key-123")
    wrapper = get_embedder(settings).client._client_wrapper
    token = wrapper._token() if callable(wrapper._token) else wrapper._token
    assert token == "test-key-123"
