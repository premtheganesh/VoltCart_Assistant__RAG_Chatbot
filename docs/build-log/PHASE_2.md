# Phase 2 — Sample data + database schema

**Goal:** give the chatbot a realistic company to answer about: 21 knowledge documents in real file formats, plus a product catalog, customers and orders in Postgres.

## What was built and why

### Knowledge documents (`sample_data/`)

| Path | What it is | Why |
|---|---|---|
| `data/catalog.json` | 20 products: specs, prices, stock, tags | Single source of truth for product facts. Every document had to agree with it |
| `source/FACTS.md` | Policy fact sheet (shipping, returns, warranty, VoltCare, payment, support) | Lets three writers work in parallel without contradicting each other. **Not ingested** |
| `source/manuals/*.md` (8) | Product manuals | Prose + spec tables + troubleshooting tables |
| `source/guides/*.md` (4) | Buying guides | Recommendations and comparison tables: the "which product is right for me" questions |
| `source/helpcenter/*.md` (9) | Help-center pages | Policy questions |
| `source/test_only/returns-and-refunds.md` | v2 returns policy (45 days, no restocking fee) | Used in Phase 3 to prove that re-indexing replaces old content |
| `docs/*.pdf / *.docx / *.html` | The rendered files the chatbot ingests | Real formats force a real ingestion pipeline. HTML pages include site navigation and footer, as real pages do, so Phase 3 must strip that boilerplate |

**Why Markdown sources plus rendering?** Markdown is easy to review and edit in git; the renderer produces realistic files from it. In a real company you would skip the sources and ingest the company's existing files directly.

### Database (`backend/`)

| File | What it is | Why |
|---|---|---|
| `app/db/models.py` | SQLAlchemy models: `products`, `customers`, `orders`, `order_items`, `shipments` | Python classes that map to tables. Check constraints enforce valid statuses, non-negative prices and positive quantities in the database itself |
| `alembic/` + `alembic.ini` | Migration tool setup; `env.py` reads the DB URL from `.env` | Schema changes become versioned, reviewable files instead of manual SQL |
| `alembic/versions/..._store_tables_....py` | First migration (auto-generated from the models, then reviewed) | `upgrade()` creates the tables; `downgrade()` removes them |
| `scripts/generate_orders.py` | Builds 30 orders with a fixed random seed | Realistic orders whose shipping costs, taxes, statuses and delivery dates follow the policy. Deterministic, so tests can rely on exact values |
| `scripts/seed.py` | Loads the JSON into Postgres in one transaction | Re-runnable: clears the store tables and reloads them |
| `scripts/render_docs.py` | Markdown to PDF (reportlab), DOCX (python-docx), HTML (template) | Deterministic output, so unchanged sources give identical files |

### Tests (59 unit + 10 database)

- `test_render_docs.py`: each renderer produces readable files (PDF text, DOCX styles and tables, HTML template).
- `test_sample_data.py`: 20 unique products; orders match the generator; totals add up; shipping follows policy; shipments match statuses; every source has valid front matter and allowed Markdown only; every product is mentioned in some document; v2 differs from v1; every rendered file exists with the right title.
- `test_store_db.py` (integration): migration applied, row counts, totals, order lookup by number + email (and a wrong email returns nothing), JSON spec queries.

### Other

- `evals/datasets/golden.jsonl` (122 cases) and `guardrails.jsonl` (32 cases), documented in `evals/datasets/README.md`. Golden cases cover every document, category, router intent, expected behavior and order status, plus tagged edge cases (multi-hop, ambiguous, false premise, typos, follow-ups, wrong-email and attempt-limit verification). The attack set includes benign look-alikes to catch over-blocking.
- `tests/test_eval_datasets.py`: checks the datasets themselves: sources exist, dollar amounts appear in the documents or a shown calculation, prices match the catalog, order cases match `orders.json`, unverified cases forbid leaking the order's tracking number and total, and every edge-case tag is used.
- New Makefile commands: `migrate`, `migration`, `seed`, `generate-orders`, `render-docs`.

## Key choices

- **Order lookups go through tools, not embeddings.** Order data is private and changes constantly, so it stays in tables and is reached through verified tools (Phase 6).
- **Product descriptions will be embedded too** (Phase 3), so "headphones for running" finds products by meaning, while exact filters (price under $150) use SQL.
- **Emails stored lowercase**, so verification compares case-insensitively.
- **Decimal for money**, never float, to avoid rounding errors like 0.1 + 0.2 = 0.30000000000000004.

## Verified

- `make test`: 59 passed. `make lint`: clean.
- On a temporary database: `make migrate`, then `make seed` twice (identical results), 10/10 integration tests, migration downgrade + upgrade. Temporary container then deleted.
- Spot checks: a PDF page rendered cleanly; every dollar amount in the documents is either a catalog price, a fact-sheet price, or a correct derived value (student discount, bundle totals).

## Concepts to know

- **Migration:** a versioned script that changes the schema. `alembic upgrade head` applies all pending ones; the `alembic_version` table records which ran.
- **ORM:** you work with Python objects (`Order`, `Product`); SQLAlchemy writes the SQL.
- **Seed data:** sample rows for development and tests.
- **JSONB:** Postgres stores specs as queryable JSON, e.g. `specs->>'water_resistance' LIKE 'IP68%'`.
- **Idempotent:** running a script twice gives the same result as running it once.
