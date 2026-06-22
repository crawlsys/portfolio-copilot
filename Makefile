# Tracker — personal portfolio + congressional research tool.

PY      := uv run python
PYTEST  := uv run pytest
UV      := uv
PNPM    := pnpm --dir web

# Load .env if present. Fall back to dev defaults so `make dev` works on a
# fresh checkout, but warn so the user knows to copy .env.example.
ifneq (,$(wildcard .env))
    include .env
    export
else
    DATABASE_URL ?= postgresql+psycopg://tracker:tracker@localhost:5432/tracker
    BROKER_MODE ?= fake
    ALLOW_LIVE_TRADING ?= false
    export
endif

.PHONY: help install dev test test-unit test-contracts test-cassettes lint type fmt check ci-clean ci openapi clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install Python + Node deps
	$(UV) sync --all-extras
	corepack enable || true
	$(PNPM) install

dev: ## Bring up deps + run migrations + start api/worker/web
	@test -f .env || echo "WARN: no .env — using dev defaults. Copy .env.example to .env for real config."
	docker compose up -d postgres garage
	DATABASE_URL=$(DATABASE_URL) $(UV) run alembic upgrade head
	@echo "migrations applied"
	@command -v overmind >/dev/null 2>&1 && overmind start -f Procfile.dev || ( \
	  echo "(overmind not installed — starting api only. Ctrl-C to stop.)" && \
	  DATABASE_URL=$(DATABASE_URL) $(UV) run uvicorn apps.api.app:create_app --factory --port 8000 )

test: ## Run full test suite (no live calls)
	$(PYTEST)

test-unit: ## Domain + application tests only (fast)
	$(PYTEST) tests/domain tests/application

test-contracts: ## Adapter contract tests (BrokerPort real vs fake)
	$(PYTEST) tests/adapters/contracts

test-cassettes: ## VCR cassette replay, no network
	VCR_RECORD_MODE=none PYTEST_DISABLE_SOCKET=1 $(PYTEST) tests/adapters

lint: ## ruff
	$(UV) run ruff check .

type: ## mypy + tsc
	$(UV) run mypy src apps
	$(PNPM) typecheck

fmt: ## ruff format + eslint fix
	$(UV) run ruff format .
	$(UV) run ruff check --fix .
	$(PNPM) lint --fix || true

check: lint type test ## lint + type + test

ci-clean: ## CI mode: disable socket, replay cassettes only
	VCR_RECORD_MODE=none PYTEST_DISABLE_SOCKET=1 $(PYTEST) --disable-socket

openapi: ## Regenerate OpenAPI client for web
	DATABASE_URL= $(UV) run python -m apps.api.openapi > web/openapi.json
	$(PNPM) openapi:generate

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache .uv-cache web/.next web/node_modules
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
