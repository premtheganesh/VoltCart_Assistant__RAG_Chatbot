# Build Phases

Each phase has: **goal**, **you do** (manual setup, so you learn it), **I build** (code), **test** (how we prove it works), and **done when**. We finish and test one phase before starting the next.

| Phase | Name | Main output |
|---|---|---|
| 0 | Environment setup (you) | Tools installed, API keys ready |
| 1 | Project skeleton + database | Repo, Postgres+pgvector in Docker, FastAPI `/health` |
| 2 | Sample data + schema | 21 VoltCart docs, products/orders seeded |
| 3 | Ingestion pipeline | Docs parsed, chunked, embedded, stored |
| 4 | Retrieval | Hybrid search + rerank + relevance gate, first retrieval eval |
| 5 | Agent v1 (RAG answers) | LangGraph router + cited answers + memory + Langfuse traces |
| 6 | Tools | Product search/compare, verified order lookup, handoff tickets |
| 7 | Guardrails | PII, Llama Guard, off-topic, grounding L1 (+ L2/output toggles) |
| 8 | API | Streaming `/chat`, feedback, admin endpoints, auth, rate limits |
| 9 | Chat UI | Next.js streaming chat with citations, product cards, feedback |
| 10 | Widget + admin panel | Embeddable widget, admin pages |
| 11 | Full evals | Golden + synthetic + adversarial sets, `make eval`, tuning |
| 12 | Hardening + deploy prep | Dockerised services, CI, README, optional free-cloud deploy |

---

## Phase 0 — Environment setup (you do this)

Already on your Mac: Docker Desktop, uv, Node 25, git, Homebrew, VS Code/Cursor, a local PostgreSQL 14 (we avoid clashing with it by using port **5433**).

1. **Start Docker Desktop** (Applications → Docker). Wait for "Engine running". Check in a terminal: `docker info` should print server details.
   *Learn:* Docker runs services (like Postgres) in isolated containers so you don't install them on your Mac directly.
2. **Install pgAdmin 4** (GUI for browsing the database): `brew install --cask pgadmin4`, or download from https://www.pgadmin.org/download/pgadmin-4-macos/. We connect it in Phase 1.
3. **Install Python 3.12 via uv:** `uv python install 3.12`
   *Learn:* uv manages Python versions and project dependencies (a fast replacement for pip + venv).
4. **Create accounts and API keys** (all free) and keep them somewhere safe (never commit them):
   - **Groq:** https://console.groq.com → API Keys → Create. (LLM)
   - **Cohere:** https://dashboard.cohere.com → API Keys → copy the trial key. (Embeddings + rerank)
   - **Langfuse:** https://cloud.langfuse.com → sign up → create organisation + project → Settings → API Keys → create (you get a public key, secret key and host URL). (Tracing)
5. **Initialise git** in the project folder: `git init` (we commit at the end of each phase).
6. **Editor extensions** (VS Code or Cursor): Python, Pylance, Ruff, ESLint, Tailwind CSS IntelliSense, Docker.

**Done when:** `docker info` works, pgAdmin opens, `uv python list` shows 3.12, and you have 3 sets of keys.

---

## Phase 1 — Project skeleton + database

- **I build:** folder structure (`backend/`, `frontend/`, `sample_data/`, `evals/`, `docs/`), `docker-compose.yml` with `pgvector/pgvector:pg16` on port 5433, `.env.example`, `Makefile`, FastAPI app with `/health` (checks DB connection), config loading, first pytest.
- **You do:** copy `.env.example` → `.env` and paste your keys; run `docker compose up -d`; in pgAdmin register a server (host `localhost`, port `5433`, user/password from `.env`) and find the `vector` extension.
- **Test:** `make test` passes; `curl localhost:8000/health` returns `{"status":"ok","db":"ok"}`.
- **Done when:** DB visible in pgAdmin and health check green.

## Phase 2 — Sample data + schema

- **I build:** Markdown sources for all 21 docs; render scripts (PDF via reportlab, DOCX via python-docx, HTML via template); `catalog.json`, `customers.json`, `orders.json`; SQLAlchemy models + Alembic migration; seed script.
- **You do:** run `make migrate` and `make seed`; browse `products`/`orders` in pgAdmin; open a few generated PDFs/DOCX; write ~20 golden questions (template provided).
- **Test:** row counts match; all 21 files exist and open.

## Phase 3 — Ingestion pipeline

- **I build:** loaders (PDF/DOCX/HTML), heading-aware chunking (~600 tokens, 80 overlap), Cohere embedder behind an interface, upsert into `documents`/`chunks` with content hashes, delete handling, `make ingest`.
- **You do:** run ingestion; inspect `chunks` in pgAdmin; run a provided SQL similarity query by hand to see vector search work.
- **Test:** unit tests (chunking, hashing); re-running ingest changes nothing; editing a file re-indexes only that file.

## Phase 4 — Retrieval

- **I build:** pgvector + full-text hybrid search, RRF fusion, Cohere rerank, relevance gate, `make ask Q="..."` CLI showing ranked chunks.
- **Test:** retrieval hit rate@5 on your golden questions (first eval baseline, target ≥ 0.85).

## Phase 5 — Agent v1 (RAG answers)

- **I build:** LangGraph state + graph: router → rewrite → retrieve → answer with citations; Postgres checkpointer memory; provider-agnostic model factory; Langfuse callback; CLI chat.
- **You do:** open Langfuse and explore a trace step by step.
- **Test:** scripted conversations (follow-ups, citations present, "I don't know" on unanswerable).

## Phase 6 — Tools

- **I build:** `search_products`, `get_product`, `compare_products`, verified `get_order_status` (interrupt/resume flow), `create_ticket`.
- **Test:** recommendation questions return suitable products; wrong email never reveals an order; 3-attempt limit; ticket appears in DB.

## Phase 7 — Guardrails

- **I build:** PII redaction, Llama Guard input check, off-topic handling, L1 grounding, L2 grounding + output check behind `.env` toggles.
- **Test:** adversarial set (injection, jailbreak, off-topic, PII) — block rate ≥ 0.90; normal questions not blocked.

## Phase 8 — API

- **I build:** FastAPI `/chat` (SSE streaming), `/feedback`, admin endpoints (upload/delete/reindex docs, tickets, conversations), JWT admin login, rate limiting, CORS.
- **You do:** try endpoints in Swagger UI at `localhost:8000/docs` and with `curl`.
- **Test:** API integration tests.

## Phase 9 — Chat UI

- **I build:** Next.js app: streaming chat, citations, product cards, thumbs up/down, handoff form.
- **You do:** `npm install`, `npm run dev`, chat at `localhost:3000`.
- **Test:** build passes; manual test script of 10 conversations.

## Phase 10 — Widget + admin panel

- **I build:** `widget.js` (iframe chat bubble), admin pages (login, documents, tickets, conversations, feedback).
- **You do:** embed the widget in a test HTML page; upload a doc through the admin panel.
- **Test:** uploaded doc becomes answerable; ticket shows in inbox.

## Phase 11 — Full evals

- **I build:** synthetic Q&A generator, adversarial set, judge metrics, thresholds file, `make eval`, results pushed to Langfuse.
- **You do:** review synthetic questions; read the eval report; we tune prompts/chunking together.
- **Test:** all PRD thresholds met.

## Phase 12 — Hardening + deploy prep

- **I build:** Dockerfiles for API and web, full compose stack, retries/fallbacks, structured logging, GitHub Actions CI (tests + evals), README.
- **You do:** create a GitHub repo and push; optionally deploy to Render/Railway + Vercel + Neon (free tiers).
- **Test:** fresh clone → `docker compose up` → working app; CI green.
