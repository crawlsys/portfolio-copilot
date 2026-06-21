# tracker

Personal portfolio management + Congressional-trade research surface.

**No live trade execution.** The system reads positions, ingests STOCK Act
disclosures, surfaces signals, and produces a daily briefing. The decision to
defer trading infrastructure followed an adversarial review of the
copy-trade-Congress alpha thesis — see
`docs/superpowers/specs/2026-06-21-congressional-portfolio-research-tool-design.md`.

## Quick start

```bash
make install
make dev            # postgres + garage + migrations + api/worker/web
```

Default broker is `FakeBroker` — no live Schwab calls. Live Schwab requires
`BROKER_MODE=schwab` plus a fresh reauth via the UI's "Reconnect Schwab"
button (Cloudflare-Access-protected).

## Layout

```
src/trading/
  domain/         pure domain — stdlib only
  application/    use cases — depends on domain + ports
  adapters/       edge code — schwab/massive/quiver/edgar/persistence/...
apps/
  api/            FastAPI
  mcp/            MCP server (read-only tools only — enforced by e2e test)
  worker/         APScheduler + outbox relay + ingest/regime/briefing jobs
  cli/            admin commands (seed-fake-account, replay-event, ...)
web/              Next.js + shadcn/ui + Tremor + Lightweight Charts
infra/k8s/        deployment manifests
tests/            mirror src structure
```

## Architectural rules (convention, not enforced)

- `trading.domain` imports only stdlib and itself.
- `trading.application` imports `domain` only.
- `trading.adapters.*` import ports + third-party libs; never `application`.
- `apps.*` is composition only.
- **No `datetime.now()` / `utcnow()` in domain or application code.** All time
  flows through `ClockPort`.
- **MCP server has no write tools.** Enforced by `tests/e2e/test_read_only_surface.py`.

## Tests

```
make test-unit         # fast, no I/O
make test-contracts    # BrokerPort real vs fake
make test-cassettes    # VCR replay, no network
RUN_LIVE_SMOKE=1 BROKER_MODE=schwab make test  # manual, read-only
```
