# Tracker

A self-hosted **portfolio management + Congressional-research tool**. It pulls
your brokerage holdings, cross-references them against U.S. Congressional trade
disclosures (STOCK Act filings), pulls market data, and produces a daily
AI-written **digest** — portfolio analytics, concentration risk, a read on the
Congressional signal, and a staged plan for deploying idle cash — delivered as a
web page plus a push notification.

> **Not investment advice.** This is a personal research tool. It performs **no
> live trade execution** — by design. Any "Action of the Day" is informational
> output from a language model over your own data; you make your own decisions.

---

## Features

- **Multi-account portfolio model** with per-account *managed* vs *self-directed*
  semantics (managed/advisor accounts are treated as hold-only; recommendations
  and cash deployment apply only to self-directed accounts).
- **All asset classes** — equities, ETFs, mutual funds, fixed income
  (CUSIP-identified treasuries), preferreds, REITs — none silently dropped.
- **Live re-pricing** with a previous-close fallback, so the portfolio
  reconciles 24/7 (not just during market hours).
- **Congressional signal** — ingests STOCK Act disclosures and flags overlaps
  with your holdings, conviction (dollar size), and disclosure lag.
- **Daily digest** — a frontier model (via OpenRouter) writes a full report;
  delivered to a dashboard page with a push-notification summary that links to
  it. Tax- and constraint-aware (won't recommend selling a hold-only account or
  realizing further gains).
- **Daily briefing** — a lighter Congressional summary via a self-hosted LLM
  gateway (fallback path).
- **Event-sourced core** — transactional outbox → durable event log → in-process
  event bus.

---

## Architecture

Domain-Driven Design with **ports & adapters** (hexagonal). The domain has no
infrastructure dependencies; adapters implement the ports.

```
src/trading/
  domain/                 value objects, entities, event catalog
  application/            use cases, UnitOfWork, EventBus, OutboxRelay
    market_data/          quote refresh
    signals/              briefing + digest generation
    portfolio/            position refresh, drift detection
  adapters/
    schwab/               brokerage holdings (BrokerPort)
    massive/              market data (MarketDataPort)
    quiver/               Congressional disclosures
    edgar/                SEC filings / company tickers
    notifications/        Pushover / ntfy (NotifierPort)
    object_store/         S3-compatible blob store (Garage)
    persistence/          SQLAlchemy models + repositories
    fake/                 in-memory broker for tests / local data
apps/
  api/                    FastAPI service (portfolio, congressional, digest, …)
  worker/                 outbox relay + single-job dispatcher (run_job)
  mcp/                    MCP server exposing tools
web/                      Next.js dashboard (App Router)
infra/k8s/                Kubernetes manifests (deployments, CronJobs)
migrations/               Alembic
```

**Ports:** `BrokerPort`, `MarketDataPort`, `NotifierPort`, `ClockPort`.
Swapping a provider means writing one adapter.

---

## Data providers

| Provider | Purpose |
|----------|---------|
| **Charles Schwab** | Brokerage accounts, positions, balances |
| **Quiver Quant** | Congressional (STOCK Act) trade disclosures |
| **Massive.com** (née Polygon) | Equity/ETF quotes (snapshot + previous-close) |
| **SEC EDGAR** | SEC filings, company ticker reference |
| **OpenRouter** | Frontier LLM for the daily digest |
| **LiteLLM** (self-hosted) | LLM gateway for the briefing (local models) |
| **Pushover** / **ntfy** | Push notifications |
| **Garage** (S3-compatible) | Blob storage for event payloads |

All provider access is read-only market/research data plus your own brokerage
data. No provider is sent trade orders.

---

## Tech stack

- **Backend:** Python 3.12+, FastAPI, SQLAlchemy 2, Pydantic, APScheduler, `uv`
- **Frontend:** Next.js 15 (App Router, server components), Tailwind, TypeScript
- **Data:** PostgreSQL, Alembic migrations
- **Runtime:** Kubernetes (k3s); scheduled work as native `CronJob`s
- **LLM:** OpenRouter (digest) + a LiteLLM gateway to local/hosted models (briefing)

---

## Configuration

All configuration is via environment variables (see `apps/common/settings.py`).
Nothing is hardcoded; secrets come from the environment.

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL DSN |
| `BROKER_MODE` | `fake` (local data file) or `schwab` (live) |
| `MASSIVE_API_KEY` | Market data |
| `QUIVER_API_KEY` | Congressional disclosures |
| `OPENROUTER_API_KEY` | Digest model |
| `DIGEST_MODEL` | e.g. `anthropic/claude-opus-4.8` |
| `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_MODEL` | Briefing LLM (e.g. `litellm`) |
| `LITELLM_BASE_URL` | LLM gateway base URL |
| `PUSH_PROVIDER` | `pushover` or `ntfy` |
| `PUSHOVER_API_TOKEN` / `PUSHOVER_USER_KEY` | Pushover credentials |
| `S3_ENDPOINT_URL` / `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Blob store |

### Holdings data (local / `fake` broker mode)

In `fake` mode the broker reads `data/holdings*.json`. **These files contain
real account data and are git-ignored** — copy the example and fill in your own:

```bash
cp data/holdings.example.json data/holdings.json
```

Each file models one account: `account_id`, `cash`, `managed` (bool), and a
`holdings` array. Mark advisor/managed accounts `"managed": true` to make them
hold-only in recommendations.

---

## Local development

```bash
# Backend
uv sync
uv run alembic upgrade head        # needs a local Postgres
uv run uvicorn apps.api.app:create_app --factory --port 8001
uv run python -m apps.worker        # outbox relay + scheduler

# Run a single scheduled job (digest, briefing, ingest, …)
uv run python -m apps.worker.run_job daily_digest

# Frontend
cd web && pnpm install && pnpm dev   # http://localhost:3001

# Tests / checks
uv run pytest -q
uv run mypy src/
cd web && pnpm typecheck && pnpm lint
```

---

## Deployment

Kubernetes manifests are in `infra/k8s/`. Scheduled work (daily digest,
Congressional ingest, market-data canary, health checks) runs as native
`CronJob`s; the long-running worker holds only the outbox relay. Holdings are
mounted via a `ConfigMap`, not baked into the image.

```bash
docker build -f docker/backend.Dockerfile -t <registry>/tracker-backend:<tag> .
docker build -f docker/web.Dockerfile -t <registry>/tracker-web:<tag> .
kubectl apply -f infra/k8s/base/
```

---

## Security & disclaimers

- **No trade execution.** The system is read-only against brokerage data.
- **No investment advice.** LLM output is informational; verify independently.
- **Your data stays yours.** Holdings files and any statement exports are
  git-ignored; never commit real account numbers, positions, or balances.
- Secrets are environment variables only — never commit credentials.

## License

MIT — see [LICENSE](LICENSE).
