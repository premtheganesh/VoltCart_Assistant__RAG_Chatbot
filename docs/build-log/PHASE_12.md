# Phase 12 — Hardening + deploy prep

**Goal:** run anywhere with one command, deploy on free tiers, and catch regressions automatically.

```
docker compose up ─► postgres (pgvector) ─► api (migrates, then serves; JSON logs) ─► web (Next.js standalone)
git push ─► GitHub Actions: lint + 1,597 tests on a fresh Postgres · web audit/typecheck/tests/build · docker build
```

## What was built and why

| Piece | What it does | Why |
|---|---|---|
| `backend/Dockerfile` | uv-locked dependencies in their own layer, non-root user, health check; runs `alembic upgrade head` and then serves | The same environment everywhere; migrations can't be forgotten; a container compromise isn't root |
| `frontend/Dockerfile` | Three stages; the runtime contains only Next.js's standalone server (`output: "standalone"`) | A small image with no dev dependencies or source. `NEXT_PUBLIC_API_URL` is a build argument because it's built into the browser code |
| `docker-compose.yml` | postgres + api + web, health-gated start order, an `uploads` volume, configurable ports | PRD: "everything starts with `docker compose up`". `make db-up` still starts only Postgres for development |
| Migration fix | The knowledge-base migration runs `CREATE EXTENSION IF NOT EXISTS vector` | It only worked because of our Docker init script: Neon, RDS and CI databases would have failed |
| `app/logging_setup.py` + middleware | `LOG_FORMAT=json`: one JSON object per line. Every request gets an id (kept from a proxy's `X-Request-ID`), returned in the response and attached to every log line of that request | Searchable logs, and a customer's "it broke at 3 pm" can be followed through all its log lines |
| `TRUSTED_PROXIES` | The visitor's IP comes from `X-Forwarded-For` only when the connection is from our own proxy (right-most untrusted hop) | Behind a load balancer, every visitor would share one rate limit. Believing the header from anyone would let a client dodge limits with a fake one |
| `/health` | Also reports `agent: ready/unavailable` | The API stays up without model keys (admin still works); now monitoring can tell |
| Filtered vector search | `SET LOCAL hnsw.iterative_scan = strict_order` when filtering | A safeguard for scale: at our size Postgres filters first and sorts exactly (verified with `EXPLAIN`); on large tables HNSW would filter after searching and could return fewer than k results |
| `.github/workflows/ci.yml` | backend (lint, migrate + seed a fresh pgvector, all tests with offline embeddings), frontend (audit, typecheck, tests, build), docker build; evals on demand with repository secrets | Every push is checked; the evals don't burn quota on every commit |
| `docs/DEPLOY.md` | Neon + Render + Vercel, or one server with `make up`; a pre-launch checklist | Deploy prep without locking into one host |

Resilience from earlier phases, now complete:
- the small model falls back to the main model
- the safety model has a backup (Prompt Guard)
- the reranker has a timeout, a fallback and a circuit breaker
- the grounding check fails open, while order verification never does
- rate limits and friendly error messages

## Verified

- **Fresh clone → `docker compose up --build --wait`:** all three containers healthy (on separate ports and project name, so the dev database was untouched).
  - seed + ingest via `docker compose run`
  - `/health` → `agent: ready`
  - admin upload saved into the volume (as the non-root user)
  - headless Chrome: the chat answered with sources, and admin listed 22 documents, with no page errors
  - JSON access logs carry the request id
- **CI conditions:** a brand-new Postgres without the init script (4 migrations, extension created), then seed, then **1,597 tests pass with no `.env` and no API keys**.

## Lessons (bugs I made and fixed this phase)

- **The request id was missing from the access log** (`"request_id": "-"`). The id was reset before the line was written. Found by reading the real container logs; fixed, with a test that the log line and the response carry the same id.
- **Root-owned upload volume:** a new Docker volume mounted on a folder that doesn't exist in the image is owned by root, and the app runs as non-root. The image now creates the folder, so the volume inherits its owner.
- **A test that couldn't fail:** the first "filtered search returns k results" test passed even with the fix removed. `EXPLAIN` showed why (exact search at this size). It's kept as an honest regression check, and the code comment says what the setting is for.

## Concepts to know

- **Image layers and caching:** copy the lockfile and install dependencies *before* copying the code, so code changes rebuild in seconds.
- **Multi-stage builds:** build in a big image, ship a small one with only what runs.
- **Health checks and `depends_on: condition: service_healthy`:** start order by readiness, not just by "the process exists".
- **12-factor config:** the same image everywhere, with settings from environment variables. Values the browser needs (`NEXT_PUBLIC_*`) are the exception: they're fixed at build time.
- **Trusting proxy headers:** `X-Forwarded-For` is just text a client can set. Only believe it from your own proxy.
