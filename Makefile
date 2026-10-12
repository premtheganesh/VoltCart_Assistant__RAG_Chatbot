# Run `make help` to list commands.
BACKEND := backend
UV := cd $(BACKEND) && uv run

.PHONY: help install db-up db-down db-reset db-logs db-shell migrate migration seed generate-orders render-docs ingest preview ask eval-retrieval eval-routing eval-guardrails eval-answers eval eval-summary synthetic chat api web-install web web-test widget-demo test test-all lint format

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

eval-routing: ## Score the router on the golden questions (writes evals/reports/routing.md)
	$(UV) python -m scripts.eval_routing $(args)

eval-guardrails: ## Run the attack set: make eval-guardrails [args="--level full"]
	$(UV) python -m scripts.eval_guardrails $(args)

eval-answers: ## Grade answers with a judge model: make eval-answers [args="--all" | args="--ids g001"]
	$(UV) python -m scripts.eval_answers $(args)

eval: ## Run every eval, then check all quality gates (evals/thresholds.toml); cached re-runs are cheap
	-$(UV) python -m scripts.eval_retrieval
	-$(UV) python -m scripts.eval_routing
	-$(UV) python -m scripts.eval_guardrails --level full
	-$(UV) python -m scripts.eval_answers
	$(UV) python -m scripts.eval_all

eval-summary: ## Check the quality gates against the latest eval results (no API calls)
	$(UV) python -m scripts.eval_all

synthetic: ## Draft new test questions from the documents for review: make synthetic [args="--n 10"]
	$(UV) python -m scripts.generate_synthetic $(args)

chat: ## Chat with the agent in the terminal: make chat [args="--debug" | args="--thread ID"]
	$(UV) python -m scripts.chat $(args)

api: ## Run the API with auto-reload on http://localhost:8000
	$(UV) uvicorn app.main:app --reload --port 8000

web-install: ## Install the chat UI's packages (frontend/node_modules)
	cd frontend && npm install

web: ## Run the chat UI with hot reload on http://localhost:3000 (needs `make api` running)
	cd frontend && npm run dev

widget-demo: ## Serve a demo store page that embeds the chat widget on http://127.0.0.1:8080
	@echo "Open http://127.0.0.1:8080 (needs make api and make web running)"
	python3 -m http.server 8080 --bind 127.0.0.1 -d sample_data/widget-demo

web-test: ## Type-check and unit-test the chat UI
	cd frontend && npm run typecheck && npm test

test: ## Run unit tests (no services needed)
	$(UV) pytest -m "not integration"

test-all: ## Run all tests, including ones that need the database
	$(UV) pytest

lint: ## Check code style
	$(UV) sh -c 'ruff check . && ruff format --check .'

format: ## Auto-fix code style
	$(UV) sh -c 'ruff check --fix . && ruff format .'
