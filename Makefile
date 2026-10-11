# Run `make help` to list commands.
BACKEND := backend
UV := cd $(BACKEND) && uv run

.PHONY: help install db-up db-down db-reset db-logs db-shell api test test-all lint format

help: ## List available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

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
