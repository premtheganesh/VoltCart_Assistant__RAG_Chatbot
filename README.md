# VoltCart Assistant

A production-style **RAG customer-support chatbot** for VoltCart, a fictional electronics store. It helps shoppers choose products, answers policy questions with citations, looks up orders only after verifying the customer, and hands off to a human when it can't help.

Everything runs on **free tiers** (Groq for the language models, Cohere for embeddings and reranking), and every provider can be swapped in `.env`.

> **Status:** Phases 1–9 of 12 are done: knowledge base, retrieval, agent, tools, guardrails, API and chat UI. Next up: the embeddable widget and admin panel, full evals, then hardening and deployment. See [docs/PHASES.md](docs/PHASES.md).

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
- **Admin API:** upload or delete documents, re-index, ticket inbox, conversations, 👎 answers.

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

## Quick start

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
make web                    # terminal 2: chat UI on http://localhost:3000
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

## Quality so far

| Metric (122 golden questions, 32 attack cases) | Result | Target |
|---|---|---|
| Retrieval hit@5 (hybrid + rerank) | 0.99 (MRR 0.93) | ≥ 0.85 |
| Routing accuracy | 0.98 (109 of 122 scored so far) | ≥ 0.90 |
| Harmless messages blocked by guardrails | 0 / 8 | 0 |
| Data leaks in attack tests | 0 | 0 |

The input safety check alone catches 15 of the 24 attacks. The other 9 belong to later layers by design (verification in code, prompt rules), and end-to-end runs handled all of them with 0 leaks. Full numbers are in [evals/reports](evals/reports). Phase 11 adds answer-quality evals.

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
  tests/          ~1,575 tests (unit + database)
frontend/         Next.js chat UI (app/, components/, lib/ with unit tests)
sample_data/      VoltCart documents, catalog, customers, orders
evals/            golden + attack datasets, reports
docs/             PRD, phases, knowledge base, build log per phase
```

## Docs

- [docs/PRD.md](docs/PRD.md): the product plan (goals, features, quality targets)
- [docs/PHASES.md](docs/PHASES.md): the 12 build phases
- [docs/KNOWLEDGE_BASE.md](docs/KNOWLEDGE_BASE.md): the sample company's data
- [docs/build-log/](docs/build-log): what each phase built, why, test results and lessons learned
- [evals/datasets/README.md](evals/datasets/README.md): eval dataset formats

## Security notes

- Secrets live only in `.env`, which is git-ignored. The browser never gets an API key; `NEXT_PUBLIC_*` variables hold no secrets.
- The LLM never writes SQL. It can only call predefined tools, and order data is released only after verification in code.
- Session ids are random and made by the server. Admin routes need a signed, expiring token. Chat and login are rate-limited.
- Uploaded files are renamed safely, parsed before they're accepted, and size-limited.
