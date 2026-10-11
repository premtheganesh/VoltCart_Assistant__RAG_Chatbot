# Phase 3 — Ingestion pipeline

**Goal:** turn the 21 documents and 20 catalog products into searchable chunks in Postgres, each with an embedding (for meaning-based search) and a full-text vector (for keyword search).

```
file ──► loader ──► blocks ──► chunker ──► chunks ──► Cohere embed ──► Postgres
(PDF/DOCX/HTML)  (headings,     (one per section,   (1024 numbers   (documents + chunks,
                  lists, tables) heading path)       per chunk)      HNSW + GIN indexes)
```

## What was built and why

| File | What it does | Why |
|---|---|---|
| `app/ingestion/loaders.py` | PDF (pdfplumber), DOCX (python-docx), HTML (BeautifulSoup) → one common list of blocks: heading / text / table | Retrieval quality is capped by parsing quality. Keeps heading levels, lists and tables; removes page headers, footers, site menus, breadcrumbs |
| `app/ingestion/chunking.py` | Heading-aware chunking: one chunk per section, long sections packed up to 600 tokens with 80 tokens overlap; big tables split by rows with the header repeated | A chunk never mixes two topics, and every chunk carries its heading path ("Stride Sport Earbuds Manual > Troubleshooting") |
| `app/llm/embeddings.py` | `get_embedder()` returns a LangChain `Embeddings` for the provider in `.env` (`cohere` or `fake`) | Switching provider is a config change. `fake` gives tests free, deterministic vectors |
| `app/ingestion/pipeline.py` | Incremental ingest: hash → skip unchanged, re-chunk changed, reuse vectors of unchanged chunks, delete removed sources; tags each chunk with the products it mentions; turns each catalog product into a small document | Re-running costs nothing; editing one paragraph re-embeds one chunk |
| `app/db/models.py` + migration | `documents` (one per source) and `chunks` (text, heading, page, products, `vector(1024)`, generated `tsvector`) with HNSW, GIN and product indexes | Vector search, keyword search and product filters all run in Postgres |
| `scripts/ingest.py` | `make ingest` (incremental), `make ingest args="--force"`, `make preview f=<file>` | `preview` shows how a file is chunked with no API calls |

## Key choices

- **Section = chunk.** Our documents are short Q&A-style sections (median 68 tokens), so most chunks are one whole section. The 600-token limit only matters for long sections; we'll tune size with the Phase 4 eval rather than guess.
- **Heading path is embedded with the text.** A troubleshooting table that never names the product is still found for "my Stride earbuds won't charge".
- **Content hashes at two levels.** File hash: skip unchanged documents. Chunk hash (text + model): reuse an existing vector. Our Cohere trial key allows about 1,000 calls a month; a full ingest takes 3, a re-run takes 0.
- **Model name stored on every chunk.** Changing `EMBED_MODEL` re-embeds everything, so vectors from two models are never compared (they'd be meaningless together).
- **All-or-nothing.** All embedding calls happen before any write, inside one transaction: if Cohere fails halfway, the database is unchanged.
- **Catalog products are documents too**, so "earbuds for running" can match a product by meaning. Stock is left out (it changes constantly; a tool will read it live in Phase 6).
- **Product tags per chunk** (longest name first, so "Nova X Pro" never also counts as "Nova X"). A manual chunk that names no product inherits the manual's product. Used for filtering in Phase 4.

## Verified

- `make test`: 1360 passed; lint clean.
- On a temporary database: migrate + seed + all 1379 tests (including 10 ingestion integration tests, run in a rolled-back transaction).
- Real Cohere run (temporary database): 41 documents, 258 chunks, 3 API calls; second run 0 calls. Sample searches:

| Question | Top result | Similarity |
|---|---|---|
| can I go swimming with my earbuds? | Stride Sport Earbuds Manual > Care and safety | 0.698 |
| ¿cuánto cuesta el envío a Hawái? (Spanish) | Shipping Policy > Do you ship to Alaska and Hawaii? | 0.662 |
| laptop for editing 4k videos | VoltBook Pro 16 User Guide > 4K video editing workflow | 0.638 |
| my bulb keeps flickering | GlowBulb guide > Factory reset (the answer, Troubleshooting, is #2) | 0.514 |

The last row is why Phase 4 adds keyword search and a reranker: pure vector search gets close but not always first.

## Bugs found and fixed

- **401 from Cohere with a valid key:** langchain-cohere turned our `SecretStr` into its masked text `**********`. Fixed by passing the raw string; a regression test checks the client holds the real key.
- **Catalog charger tagged with 3 products:** its specs list compatible laptops. Catalog chunks now keep only their own SKU.
- **PDF numbered steps merged into one paragraph:** reportlab draws "1" without a dot; detected by the gap after the number instead.

## Concepts to know

- **Embedding:** a list of 1024 numbers representing meaning. Similar meaning → vectors pointing the same way (cosine similarity near 1).
- **`search_document` vs `search_query`:** Cohere embeds stored chunks and questions slightly differently, which improves matching. LangChain picks the right one.
- **HNSW index:** a graph that finds nearest vectors without comparing against every row. **GIN index:** fast lookup for full-text and array columns.
- **`tsvector`:** the words of a chunk, stemmed ("fees" → "fee"), for keyword search. Postgres updates it automatically (generated column).
- **Incremental indexing:** only process what changed, detected with content hashes.
