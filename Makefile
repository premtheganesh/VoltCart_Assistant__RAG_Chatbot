# Run `make help` to list commands.
BACKEND := backend
UV := cd $(BACKEND) && uv run

.PHONY: help install db-up db-down db-reset db-logs db-shell migrate migration seed generate-orders render-docs ingest preview ask eval-retrieval api test test-all lint format

help: ## List available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install backend dependencies into backend/.venv
	cd $(BACKEND) && uv sync

db-up: ## Start Postgres + pgvector (Docker) and wait until healthy
	docker compose up -d --wait postgres

db-down: ## Stop Postgres (data is kept)
	docker compose down

db-reset: ## Stop Postgres AND delete all its data
	docker compose down -v

db-logs: ## Follow Postgres logs
	docker compose logs -f postgres

db-shell: ## Open a psql shell inside the container
	docker compose exec postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

migrate: ## Apply database migrations (create/update tables)
	$(UV) alembic upgrade head

migration: ## Create a new migration from model changes: make migration m="describe change"
	$(UV) alembic revision --autogenerate -m "$(m)"

seed: ## Load sample products, customers and orders into the database (replaces existing)
	$(UV) python -m scripts.seed

generate-orders: ## Regenerate sample_data/data/orders.json (deterministic)
	$(UV) python -m scripts.generate_orders

render-docs: ## Render Markdown sources into PDF / DOCX / HTML documents
	$(UV) python -m scripts.render_docs

ingest: ## Embed new/changed documents + catalog into the knowledge base: make ingest args="--force"
	$(UV) python -m scripts.ingest $(args)

preview: ## Show how one file is chunked, no API calls: make preview f=sample_data/docs/shipping-policy.html
	$(UV) python -m scripts.ingest --preview "$(f)"

ask: ## Show retrieval results for a question: make ask q="can I swim with the stride?" [mode=keyword]
	$(UV) python -m scripts.ask "$(q)" $(if $(mode),--mode $(mode))

eval-retrieval: ## Score retrieval on the golden questions (writes evals/reports/retrieval.md)
	$(UV) python -m scripts.eval_retrieval $(args)

api: ## Run the API with auto-reload on http://localhost:8000
	$(UV) uvicorn app.main:app --reload --port 8000

test: ## Run unit tests (no services needed)
	$(UV) pytest -m "not integration"

test-all: ## Run all tests, including ones that need the database
	$(UV) pytest

lint: ## Check code style
	$(UV) sh -c 'ruff check . && ruff format --check .'

format: ## Auto-fix code style
	$(UV) sh -c 'ruff check --fix . && ruff format .'
