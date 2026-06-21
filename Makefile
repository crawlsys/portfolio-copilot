# Tracker — personal portfolio & congressional research tool.
# (No `task` runner on this box; Make is universal.)

PY      := uv run python
PYTEST  := uv run pytest
UV      := uv
PNPM    := pnpm --dir web

.PHONY: help install dev test lint type fmt check ci-clean ci openapi clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install Python + Node deps
	$(UV) sync --all-extras
	corepack enable || true
	$(PNPM) install

dev: ## Bring up deps (postgres + garage) + run migrations + start api/worker/web
	docker compose up -d postgres garage
	$(UV) run alembic upgrade head
	$(UV) run python -m apps.cli seed-fake-account
	overmind start -f Procfile.dev || true

test: ## Run full test suite (no live calls)
	$(PYTEST)

test-unit: ## Domain + application tests only (fast)
	$(PYTEST) tests/domain tests/application

test-contracts: ## Adapter contract tests (BrokerPort real vs fake)
	$(PYTEST) tests/adapters/contracts

test-cassettes: ## VCR cassette replay, no network
	$(PYTEST) tests/adapters --disable-socket
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
	$(UV) run python -m apps.api.openapi > web/openapi.json
	$(PNPM) openapi:generate

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache .uv-cache web/.next web/node_modules
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
