# Phase 1 — Project skeleton + database

**Goal:** a running database with vector search, and a minimal API that proves it can talk to it. Every later phase builds on this.

## What was built and why

| File | What it is | Why |
|---|---|---|
| `docker-compose.yml` | Defines the `postgres` service using the `pgvector/pgvector:pg16` image, port `5433 → 5432`, a named volume, and a health check | One command starts an identical database on any machine. The volume keeps data when the container restarts. Port 5433 avoids your local PostgreSQL 14 on 5432 |
| `docker/postgres/init/01-extensions.sql` | `CREATE EXTENSION vector;` | Postgres runs scripts in this folder the first time the database is created, so pgvector is always enabled |
| `.env.example` | Template of every setting (DB, Groq, Cohere, Langfuse) | Documents what config exists. The real `.env` holds secrets and is git-ignored |
| `.gitignore` | Ignores `.env`, `.venv`, caches, `node_modules` | Keeps secrets and generated files out of git |
| `backend/pyproject.toml` + `uv.lock` | Python project definition and exact locked versions | `uv sync` recreates the same environment anywhere |
| `backend/app/config.py` | `Settings` class (pydantic-settings) that reads `.env` | One typed place for configuration; API keys are `SecretStr` so they never print in logs |
| `backend/app/db/session.py` | SQLAlchemy engine (psycopg 3 driver) + per-request session dependency `DbSession` | Standard, connection-pooled DB access; `pool_pre_ping` recovers if the container restarts |
| `backend/app/api/health.py` | `GET /health` → checks `SELECT 1` and the pgvector version; returns 503 if the DB is down | Load balancers, Docker and humans use it to know the service is really working, not just running |
| `backend/app/main.py` | FastAPI app + logging setup | The API entry point that later phases add routes to |
| `backend/tests/test_health.py` | 3 unit tests (DB mocked) + 1 integration test (real DB) | Unit tests run anywhere in under a second; the integration test proves the real container works |
| `Makefile` | Short commands: `make db-up`, `make api`, `make test`, ... | You don't have to remember long Docker/uv commands. `make help` lists them |
| `.vscode/settings.json` | Points VS Code at `backend/.venv`, enables pytest and Ruff format-on-save | Editor uses the right Python and runs tests from the Testing sidebar |

## Key choices

- **psycopg 3** (not psycopg2): modern driver, and the one LangGraph's Postgres memory uses later.
- **Sync SQLAlchemy for now:** simpler to learn and debug; FastAPI runs sync routes in a thread pool, which is fine at our scale.
- **Ruff:** one fast tool for linting and formatting.
- **Unit vs integration tests:** `make test` needs nothing running; `make test-all` also checks the real database.

## Verified

- `make test`: 3 passed.
- `make lint`: all checks passed.
- Integration test and `/health` against a temporary container: `{"status":"ok","db":"ok","pgvector":"0.8.7"}` (temporary container then deleted).

## Concepts to know

- **Container vs image:** the image is the template (`pgvector/pgvector:pg16`); the container is a running instance of it.
- **Volume:** storage that lives outside the container, so deleting the container doesn't delete data (`make db-reset` deletes both).
- **Port mapping `5433:5432`:** your Mac's port 5433 forwards to port 5432 inside the container.
- **Dependency injection (`DbSession`):** FastAPI creates a DB session for each request and closes it afterwards; tests swap it for a fake.
