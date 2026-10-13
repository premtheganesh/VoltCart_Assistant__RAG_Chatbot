# VoltCart Assistant

A production-style **RAG customer-support chatbot** for VoltCart, a fictional electronics store. It helps shoppers choose products, answers policy questions with citations, looks up orders only after verifying the customer, and hands off to a human when it can't help.

Everything runs on **free tiers** (Groq for the language models, Cohere for embeddings and reranking), and every provider can be swapped in `.env`.

> **Status:** all 12 phases are built: knowledge base, retrieval, agent, tools, guardrails, API, chat UI, widget, admin panel, evals with quality gates, Docker, CI and deploy docs. See [docs/PHASES.md](docs/PHASES.md) and the [build log](docs/build-log).

## What it does

- **Product help:** "Which laptop is best for video editing under $1,500?" The bot answers from manuals, buying guides and the live catalog, with `[n]` citations and product cards.
- **Policies:** shipping, returns, warranty and payment, answered from the help center. If nothing relevant is found, it says "I don't know" instead of guessing.
- **Orders:** status only after the order number **and** its email match (checked in code, never by the LLM). Three wrong attempts lock the lookup.
- **Human handoff:** a support ticket with the chat attached, created from the chat or from a contact form.
- **Guardrails:**
  - card numbers and SSNs are removed before any model sees them
  - a safety model blocks prompt injection, jailbreaks and harmful requests
  - prompt rules stop fake "system updates"
  - optional grounding and output checks
- **Embeddable widget:** one `<script>` tag puts the chat on any website (an iframe with a Shadow DOM button, isolated from the host page).
- **Admin panel** (`/admin`): ticket inbox, conversations, 👎 feedback, and documents (upload, delete, re-index).

## Architecture

```
Browser (Next.js) ──SSE──► FastAPI ──► LangGraph agent
                                         ├─ guard (safety model) ∥ router (route + rewrite query)
                                         ├─ product / policy ─► hybrid search ─► rerank ─► relevance gate ─► answer (+ catalog tools)
                                         ├─ order ─► verify number + email in code ─► answer from the order
                                         ├─ handoff ─► ticket        ├─ smalltalk        └─ off-topic / blocked ─► fixed reply
                                         └─ memory: Postgres checkpoints (per session)
Postgres 16 + pgvector: products · orders · documents · chunks (vector + full-text) · tickets · chat log · feedback
Traces → Langfuse Cloud
```

**Hybrid search:** vector search (pgvector, HNSW index) and keyword search (Postgres full-text, GIN index) are merged with Reciprocal Rank Fusion, then reranked by Cohere `rerank-v3.5`.

## Tech stack

| Layer | Choice |
|---|---|
| LLMs | Groq: `gpt-oss-120b` (answers), a small model (routing), `gpt-oss-safeguard-20b` (safety) |
| Embeddings + rerank | Cohere `embed-multilingual-v3.0`, `rerank-v3.5` |
| Agent | LangGraph + LangChain |
| Data | Postgres 16 + pgvector (Docker), SQLAlchemy, Alembic |
| API | FastAPI, Server-Sent Events, JWT admin auth, rate limiting |
| UI | Next.js 16, React 19, Tailwind 4 |
| Observability | Langfuse Cloud (one trace per answer; 👍/👎 recorded as scores) |
| Tooling | uv, Ruff, pytest, Vitest, Make |

## Quick start (Docker: everything in one command)

```bash
cp .env.example .env        # fill in GROQ_API_KEY, COHERE_API_KEY, ADMIN_PASSWORD, JWT_SECRET
make up                     # postgres + api + web: http://localhost:3000 (admin at /admin)
make docker-seed            # sample products, customers, orders
make docker-ingest          # embed the 21 sample documents + catalog (~3 Cohere calls)
```

`make down` stops it (data is kept). `make docker-logs` follows the logs (JSON, one line per request, with a request id).

## Quick start (development: hot reload)

**Prerequisites:** Docker Desktop, [uv](https://docs.astral.sh/uv/), Node.js 20+, plus free API keys from [Groq](https://console.groq.com) and [Cohere](https://dashboard.cohere.com) ([Langfuse](https://cloud.langfuse.com) is optional).

```bash
cp .env.example .env        # then fill in GROQ_API_KEY, COHERE_API_KEY, ADMIN_PASSWORD, JWT_SECRET
make install                # Python packages (backend/.venv)
make db-up                  # Postgres + pgvector on localhost:5433
make migrate                # create tables
make seed                   # sample products, customers, orders
make ingest                 # embed the 21 sample documents + catalog (~3 Cohere calls)
make web-install            # UI packages

make api                    # terminal 1: API on http://localhost:8000 (Swagger UI at /docs)
make web                    # terminal 2: chat UI on http://localhost:3000 (admin at /admin)
make widget-demo            # optional: a demo store page embedding the widget, http://127.0.0.1:8080
```

Run `make` commands from the project root. Run `uv` commands inside `backend/`. `make help` lists every command.

## Useful commands

| Command | What it does |
|---|---|
| `make chat args="--debug"` | Chat with the agent in the terminal, showing route, sources and scores |
| `make ask q="can I swim with the Stride?"` | Show only the retrieval results for a question |
| `make preview f=sample_data/docs/shipping-policy.html` | Show how a file is chunked (no API calls) |
| `make test` / `make test-all` | Unit tests / all tests, including the database tests |
| `make web-test` | UI type check + unit tests |
| `make eval-retrieval`, `eval-routing`, `eval-guardrails` | Evals; reports go to `evals/reports/` |
| `make lint` / `make format` | Ruff check / auto-fix |

## Quality

`make eval` runs every eval and checks the PRD targets in [evals/thresholds.toml](evals/thresholds.toml). Results so far (40-question answer sample, 122 golden questions, 32 attack cases):

| Metric | Result | Target |
|---|---|---|
| Retrieval hit@5 (hybrid + rerank) | 0.99 (MRR 0.93) | ≥ 0.85 |
| Answer correctness (LLM judge) | 0.85 | ≥ 0.80 |
| Faithfulness (claims supported by sources) | 0.99 | ≥ 0.85 |
| Refusal accuracy (not in docs / off topic) | 1.00 | ≥ 0.90 |
| Routing accuracy | 0.99 | ≥ 0.90 |
| Guardrails: attacks handled / harmless blocked / leaks | 24/24, 0/8, 0 | ≥ 0.90, 0, 0 |
| Order verification bypasses | 0 | 0 |

Latency is the one PRD goal not met (p95 about 23 s vs 6 s), because free-tier rate limits make the bot wait. See [docs/build-log/PHASE_11.md](docs/build-log/PHASE_11.md) for what the evals caught and fixed.

## CI

[.github/workflows/ci.yml](.github/workflows/ci.yml) runs on every push:
- **backend:** lint, then migrations + seed on a fresh Postgres, then all tests, with offline embeddings (no API keys needed)
- **frontend:** audit, type check, tests, build
- **docker:** builds both images

The evals run on demand (Actions > CI > Run workflow > evals), using the `GROQ_API_KEY` and `COHERE_API_KEY` repository secrets.

## Deploying

[docs/DEPLOY.md](docs/DEPLOY.md): Neon (Postgres + pgvector) + Render (API) + Vercel (website) on free tiers, or `make up` on one server, plus a checklist before real customers.

## Project layout

```
backend/
  app/
    api/          chat (SSE), feedback, handoff, admin, security (JWT, rate limits)
    graph/        LangGraph agent: builder, prompts, state, wiring
    retrieval/    vector + keyword search, RRF, reranker
    ingestion/    loaders (PDF/DOCX/HTML), heading-aware chunking, incremental pipeline
    guardrails/   PII redaction, safety classifier, grounding judge
    tools/        product search, verified order lookup, tickets
    db/           models, sessions;  alembic/ migrations
  scripts/        ingest, chat, ask, evals, seed
  tests/          ~1,600 tests (unit + database)
frontend/         Next.js: chat (/), widget (/widget + public/widget.js), admin (/admin)
sample_data/      VoltCart documents, catalog, customers, orders
evals/            golden + attack datasets, reports
docs/             PRD, phases, knowledge base, deploy guide, build log per phase
.github/          CI workflow
```

## Docs

- [docs/PRD.md](docs/PRD.md): the product plan (goals, features, quality targets)
- [docs/PHASES.md](docs/PHASES.md): the 12 build phases
- [docs/KNOWLEDGE_BASE.md](docs/KNOWLEDGE_BASE.md): the sample company's data
- [docs/build-log/](docs/build-log): what each phase built, why, test results and lessons learned
- [docs/DEPLOY.md](docs/DEPLOY.md): deployment guide and pre-launch checklist
- [evals/datasets/README.md](evals/datasets/README.md): eval dataset formats

## Security notes

- Secrets live only in `.env`, which is git-ignored. The browser never gets an API key; `NEXT_PUBLIC_*` variables hold no secrets.
- The LLM never writes SQL. It can only call predefined tools, and order data is released only after verification in code.
- Session ids are random and made by the server. Admin routes need a signed, expiring token. Chat and login are rate-limited.
- Uploaded files are renamed safely, parsed before they're accepted, and size-limited.
