# Tracker

A self-hosted **portfolio management + Congressional-research tool** with
**agent-driven, gated order execution**. It pulls your brokerage holdings,
cross-references them against U.S. Congressional trade disclosures (STOCK Act
filings), pulls market data, produces a daily AI-written **digest**, and lets
an agent (you, via a CLI) place live equity orders through a preview → confirm
→ submit flow with a hard confirmation gate.

![Portfolio Dashboard](docs/screenshots/portfolio.png)

> **Not investment advice.** This is a personal research tool. LLM output is
> informational; you make your own decisions. Order placement is gated: no
> single call both builds and submits an order.

---

## Features

- **Live brokerage integration** — OAuth against Charles Schwab; reads
  balances, positions, orders, and transactions from your real accounts.
  Non-equity instruments (Treasury CUSIPs, mutual funds, preferreds) are
  coerced to FIXED_INCOME — none silently dropped.
- **Agent-driven order placement** — place live MARKET/LIMIT equity orders via
  a two-step gated flow (preview → confirm → submit). The broker's
  `preview_order` validates acceptance without submitting; `submit_place_order`
  is the only path that places a live order. See [Trading](#trading).
- **Multi-account portfolio model** with per-account *managed* vs
  *self-directed* semantics (managed/advisor accounts are treated as hold-only).
- **All asset classes** — equities, ETFs, mutual funds, fixed income
  (CUSIP-identified treasuries), preferreds, REITs.
- **Live re-pricing** with a previous-close fallback, so the portfolio
  reconciles 24/7 (not just during market hours).
- **Congressional signal** — ingests STOCK Act disclosures and flags overlaps
  with your holdings, conviction (dollar size), and disclosure lag.

  ![Congressional Feed](docs/screenshots/congressional.png)

- **Portfolio overlap view** — disclosures grouped by the tickers you actually
  hold, with conviction and lag context.

  ![Portfolio Overlap](docs/screenshots/overlap.png)

- **Daily digest** — a frontier model writes a full report: portfolio
  analytics, concentration risk, a read on the Congressional signal, and a
  staged plan for deploying idle cash. Delivered to a dashboard page plus a
  push-notification summary that links to it.

  ![Daily Digest](docs/screenshots/digest.png)

- **Daily briefing** — a lighter Congressional summary via a self-hosted LLM
  gateway (fallback path), formatted for mobile push (colored BUY/SELL lines,
  not raw markdown).
- **Event-sourced core** — transactional outbox → durable event log → in-process
  event bus. Every order submission is recorded in an append-only audit log.

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
    execution/            order placement (preview → confirm → submit)
  adapters/
    schwab/               brokerage: holdings + order placement (BrokerPort)
      broker.py           OAuth, reads, preview/submit/cancel orders
      orders.py           equity order spec builder (market/limit)
      oauth_store.py      token persistence
    massive/              market data (MarketDataPort)
    quiver/               Congressional disclosures
    edgar/                SEC filings / company tickers
    notifications/        Pushover / ntfy (NotifierPort)
    object_store/         S3-compatible blob store (Garage)
    persistence/          SQLAlchemy models + repositories
    fake/                 in-memory broker for tests / local data
apps/
  api/                    FastAPI service (portfolio, congressional, digest, audit)
  worker/                 outbox relay + single-job dispatcher (run_job)
  mcp/                    MCP server exposing read-only tools
web/                      Next.js dashboard (App Router)
infra/k8s/                Kubernetes manifests (deployments, CronJobs)
migrations/               Alembic
scripts/                  schwab_login.py, place_order.py, seed_demo.py, screenshots.mjs
```

**Ports:** `BrokerPort` (reads + gated trading), `MarketDataPort`,
`NotifierPort`, `ClockPort`. Swapping a provider means writing one adapter.

---

## Trading

Order placement is a **two-step gated flow** — no single method both builds
and submits an order:

1. **Preview** — builds the spec, validates buying power, calls Schwab's
   `preview_order` (validates acceptance WITHOUT submitting), and shows you the
   exact spec + estimated cost + buying-power impact.
2. **Confirm** — a hard gate. The CLI prompts `Type 'yes' to confirm`.
3. **Submit** — re-validates (buying power may have moved), calls
   `place_order`, captures the order ID, and writes an audit record.

Dollar-amount orders compute whole-share quantities from a live quote and
**round down** — the order never over-buys.

```bash
# Buy ~$3000 of VTI at market in the self-directed account
uv run python scripts/place_order.py --account ****3450 --buy VTI --usd 3000 --market

# Buy 100 shares of AAPL at a $230 limit
uv run python scripts/place_order.py --account ****3450 --buy AAPL --qty 100 --limit 230
```

**Deliberately absent:** auto-execution (no saga that places orders without a
human in the loop) and MCP trading tools (the MCP server exposes read-only
tools only). Trading goes through the CLI/API two-step flow.

---

## Data providers

| Provider | Purpose |
|----------|---------|
| **Charles Schwab** | Brokerage accounts, positions, balances, **order placement** |
| **Quiver Quant** | Congressional (STOCK Act) trade disclosures |
| **Massive.com** (née Polygon) | Equity/ETF quotes (snapshot + previous-close) |
| **SEC EDGAR** | SEC filings, company ticker reference |
| **LiteLLM** (self-hosted) | LLM gateway — `local-strong` (Qwen3) for both digest + briefing |
| **Pushover** / **ntfy** | Push notifications |
| **Garage** (S3-compatible) | Blob storage for event payloads |

All provider access is your own brokerage data, read-only market/research
data, and (for trading) gated order placement against your own account.

---

## Tech stack

- **Backend:** Python 3.12+, FastAPI, SQLAlchemy 2, Pydantic, APScheduler, `uv`
- **Frontend:** Next.js 15 (App Router, server components), Tailwind, Tremor, TypeScript
- **Data:** PostgreSQL, Alembic migrations
- **Runtime:** Kubernetes (k3s); scheduled work as native `CronJob`s
- **LLM:** LiteLLM gateway to self-hosted models (Qwen3 on local GPU)

---

## Configuration

All configuration is via environment variables (see `apps/common/settings.py`).
Nothing is hardcoded; secrets come from the environment.

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL DSN |
| `BROKER_MODE` | `fake` (local data file) or `schwab` (live) |
| `HOLDINGS_FILE` | Override holdings file for fake broker (default `data/holdings.json`) |
| `MASSIVE_API_KEY` | Market data |
| `QUIVER_API_KEY` | Congressional disclosures |
| `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_MODEL` | LLM gateway (e.g. `litellm` / `local-strong`) |
| `LITELLM_BASE_URL` | LLM gateway base URL |
| `PUSH_PROVIDER` | `pushover` or `ntfy` |
| `PUSHOVER_API_TOKEN` / `PUSHOVER_USER_KEY` | Pushover credentials |
| `SCHWAB_CLIENT_ID` / `SCHWAB_CLIENT_SECRET` | Schwab OAuth app credentials |
| `SCHWAB_REDIRECT_URI` | OAuth callback (`https://127.0.0.1:8080/callback`) |
| `SCHWAB_TOKEN_PATH` | Path to the schwab-py token file (default `/etc/schwab/token.json`) |
| `S3_ENDPOINT_URL` / `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Blob store |

### Schwab OAuth setup

```bash
# Register a callback URL of https://127.0.0.1:8080/callback in the Schwab
# developer portal, then run the login flow locally (it opens a browser):
uv run python scripts/schwab_login.py
# Token is written to ~/.tracker/schwab_token.json — load it into k8s:
kubectl create secret generic tracker-schwab-token -n tracker \
  --from-file=token.json=$HOME/.tracker/schwab_token.json \
  --dry-run=client -o yaml | kubectl apply -f -
```

> ⚠️ **The refresh token expires in 7 days** (Schwab hard cap). Re-run
> `schwab_login.py` before then, or wire up the token-canary job to alert you.

### Holdings data (local / `fake` broker mode)

In `fake` mode the broker reads `data/holdings.json` (override with
`HOLDINGS_FILE`). **These files contain real account data and are git-ignored**
— copy the example and fill in your own:

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

## Demo data + screenshots

Generate anonymized demo data and capture dashboard screenshots for the README:

```bash
# 1. Boot a throwaway Postgres + run migrations
docker run -d --name tracker-demo-pg --rm -p 5432:5432 \
  -e POSTGRES_USER=tracker -e POSTGRES_PASSWORD=tracker -e POSTGRES_DB=tracker \
  postgres:16-alpine
DATABASE_URL="postgresql+psycopg://tracker:tracker@localhost:5432/tracker" \
  uv run alembic upgrade head

# 2. Seed demo data (~$100k anonymized portfolio, 20 disclosures, 1 digest)
DATABASE_URL="postgresql+psycopg://tracker:tracker@localhost:5432/tracker" \
  uv run python scripts/seed_demo.py

# 3. Start the stack in demo mode
DATABASE_URL="postgresql+psycopg://tracker:tracker@localhost:5432/tracker" \
  BROKER_MODE=fake HOLDINGS_FILE=data/holdings-demo.json MASSIVE_API_KEY="" \
  uv run uvicorn apps.api.app:create_app --factory --port 8001 &
NEXT_PUBLIC_ACCOUNT_IDS="demo-account:Demo Brokerage" \
  NEXT_PUBLIC_API_BASE_URL="http://localhost:8001" \
  (cd web && npx next dev -p 3001) &

# 4. Capture screenshots
node scripts/screenshots.mjs --viewport   # → docs/screenshots/*.png
```

The demo portfolio (`data/holdings-demo.json`) is synthetic and contains no
real account data.

---

## Deployment

Kubernetes manifests are in `infra/k8s/`. Scheduled work (daily digest,
Congressional ingest, market-data canary, health checks) runs as native
`CronJob`s; the long-running worker holds only the outbox relay. Holdings are
mounted via a `ConfigMap` (not baked into the image — node containerd can serve
stale image layers across rebuilds). The Schwab OAuth token is mounted as a
secret at `/etc/schwab/token.json`.

```bash
docker build -f docker/backend.Dockerfile -t <registry>/tracker-backend:<tag> .
docker build -f docker/web.Dockerfile -t <registry>/tracker-web:<tag> .
kubectl apply -f infra/k8s/base/
```

---

## Security & disclaimers

- **Gated trading.** Order placement is a two-step flow: `preview_order`
  validates without submitting; `submit_place_order` is the only live path,
  and the CLI requires explicit confirmation. Every submission is audited.
- **No auto-execution.** There is no saga that places orders without a human
  confirming each one. MCP tools are read-only.
- **No investment advice.** LLM output is informational; verify independently.
- **Your data stays yours.** Holdings files and statement exports are
  git-ignored; never commit real account numbers, positions, or balances.
- Secrets are environment variables only — never commit credentials.

## Roadmap

- **Recommendation ledger** — persist the daily "Action of the Day" as a
  structured recommendation (verb/ticker/amount/window/status) with continuity:
  the digest LLM sees prior recommendations and must explicitly call out when
  it pivots. Auto-detect acted-on recommendations from Schwab position deltas.

---

## License

MIT — see [LICENSE](LICENSE).
