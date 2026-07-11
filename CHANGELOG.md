# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Changed
- **Secrets are now sourced entirely from Bitwarden Secrets Manager via the
  secrets-store CSI driver** — the plaintext `infra/k8s/base/secrets.yaml`
  Secret manifest is **removed**. A new `infra/k8s/base/secretproviderclass.yaml`
  (provider `bitwarden`) references BWS UUIDs and syncs both `tracker-secrets`
  (env) and `tracker-schwab-token` (`token.json`). `api`/`worker`/`mcp` mount
  the SPC CSI volume (`/mnt/secrets`) to drive the sync; CronJobs free-ride on
  the always-on api/worker keepers. This codifies the live cluster setup (which
  had drifted from git) and eliminates the committed-Secret antipattern.
  Prerequisite: a `bws-token` Secret in the `tracker` namespace.
- **`scripts/schwab_login.py`** now pushes the refreshed `token.json` to the
  `TRACKER_SCHWAB_TOKEN_JSON` BWS secret (`bws secret edit`) instead of printing
  a `kubectl create secret` command — one source of truth, picked up on the next
  pod roll. The static Schwab app creds already live in BWS and sync like any
  other env secret.

### Added
- **Advisor council** (adopted from virattt/ai-hedge-fund v2, MIT): persona
  LLM analysts form point-in-time views over fundamentals snapshots.
  - `trading.application.advisors`: `FundamentalsSnapshot` (filing-date-
    filtered history + derived aggregates, `content_hash` cache key),
    `AdvisorAgent` base with the v2 failure contract (data errors propagate;
    LLM/parse failures abstain), `BuffettAdvisor` persona (prompt ported
    verbatim), OpenAI-compatible litellm transport (`ADVISOR_MODEL`, default
    `advisor-frontier` alias; `LITELLM_BASE_URL`).
  - Massive fundamentals adapter: income/balance/cash-flow statement
    endpoints (`stocks/financials/v1/*`, requires the "Financials & Ratios
    Expansion" entitlement), point-in-time on `filing_date.lte`, per-period
    ratios computed from statements, market cap / P-E priced at the daily
    close on each filing date.
  - `advisor_views` table (migration `0004_advisor_views`) — cache + audit
    trail: unique (advisor, model, snapshot_hash) so an unchanged snapshot
    never re-pays the LLM; every view stores its exact prompts + raw response.
  - `advisor_views` CronJob (6:30 AM ET, before the digest); the daily digest
    and digest chat contexts gain an "Advisor Council" block; MCP gains
    read-only `list_advisors` / `get_advisor_views` tools.
  - Domain: `SignalKind.ADVISOR_VIEW` + `AdvisorView.to_signal()` projection.
  - **Personas: Buffett, Munger, Graham, Burry** — a fundamentals-driven value
    council. Each is one file (name + strict-JSON system prompt); registry in
    `advisors/__init__.py`. A registry test asserts every persona honours the
    agent contract (schema + no-lookahead rule + forms a valid view).

### Changed
- Parameterized the LiteLLM gateway default (`LITELLM_BASE_URL` /
  `DEFAULT_LITELLM_BASE_URL`) to a generic `http://localhost:4000` — the real
  endpoint is injected via env from BWS in production, not hardcoded.
- **Recommendation ledger**: the daily digest LLM now has memory of its own
  prior advice (`recommendations` table, migration `0003_recommendations`).
  Each digest run: expires past-due recs, auto-detects acted-on BUYs by
  diffing live Schwab positions/cash against issue-time baselines (±15%
  tolerance), feeds open/resolved recs back into the prompt with continuity
  rules, and extracts a structured `<<<RECOMMENDATION>>>` block from the
  model output (stripped before display; malformed block → HOLD fallback,
  the digest is never lost). Pivots must be explicit via `supersedes:` —
  the prior rec is marked `superseded` and linked. New setting:
  `SELF_DIRECTED_ACCOUNT_ID` (empty → detection skipped, best-effort).
- **Digest chat** — an interactive, context-aware chatbot on the `/digest` page.
  Streams (SSE) answers from a model that sees the same context the daily digest
  is built from (portfolio, holdings, congressional signal, market regime) plus
  the **last 5 digests**, so it knows what was already recommended/held (e.g.
  won't re-suggest VTI if it's already bought). Backend `POST /digest/chat`
  (`apps/api/routes/digest_chat.py`) reuses the digest's context builders; a
  same-origin Next route handler (`web/src/app/api/digest/chat/route.ts`) proxies
  to the internal API so the browser never makes a cross-origin call; the
  `DigestChat` client component has a model picker (Opus 4.8 / Sonnet 4.6 /
  Gemini Flash). Model allowlist + in-process rate limit guard cost. History is
  ephemeral (browser-only).
- **Web `/healthz` probe endpoint**: lightweight route returning 200 without
  calling the backend API, so pod readiness/liveness is decoupled from upstream
  latency (`web/src/app/healthz/route.ts`).
- **MCP streamable-HTTP transport + in-cluster Deployment**: the transport the
  server docstring always promised. `MCP_TRANSPORT=http` serves streamable HTTP
  on `MCP_PORT` (default 8765) at `/mcp`; new `infra/k8s/base/mcp.yaml`
  (Deployment + ClusterIP Service, deliberately no Ingress — the MCP protocol
  carries no auth and the tools serve live brokerage data). The MCP composition
  is now wired from `apps.common.settings` like the API/worker, so the pod sees
  the real broker/DB/market-data instead of raw-env `fake`/empty defaults.

### Fixed
- **MCP tools invisible to agents (handler overwrite)**: each tool module
  registered its own `@server.list_tools()`/`@server.call_tool()` on the shared
  low-level `Server`, which keeps ONE handler per request type — the
  last-registered module (briefing) silently replaced the rest, so connected
  agents saw only briefing tools and could not answer portfolio questions.
  Tool modules now expose passive `TOOLS` + `handle()` and
  `apps/mcp/tools/__init__.py` owns a single aggregated registration; a
  regression test asserts one live ListTools request serves every module.
- **`make ci-clean` was broken twice over**: it passed `--disable-socket`
  (pytest-socket is not a dependency; the conftest env-var blocker is the real
  mechanism) and it inherited the Makefile's `.env`/dev-default `DATABASE_URL`,
  un-skipping DB-backed tests that then fail on any machine without a local
  Postgres. The target now clears `DATABASE_URL` and drops the flag, matching
  CI's bare-pytest behavior.
- **mypy cleanup**: `generate_briefing._render_table_block` shadowed a loop
  variable with its `cell()` helper (8 spurious errors); the digest's
  swallowed model-call failure now logs a warning instead of `pass`.
- **API pod missing the self-directed ledger mount**: the `tracker-holdings`
  ConfigMap was mounted into the API deployment with only `holdings.json` (joint
  book), not `holdings-individual.json`. The digest CronJob mounts both, so
  generated digests were fine, but the new live digest chat reads the individual
  ledger in the API pod and saw an empty/$0 account. Added the
  `holdings-individual.json` subPath mount to `infra/k8s/base/api.yaml`.
- **trackdash 502 (web pod never Ready)**: the readiness probe targeted `/`
  with a 1s timeout, but the homepage is `force-dynamic` and does a 1-2s
  server-side API fetch, so the probe always timed out → pod stuck `0/1` →
  ingress 502. Repointed readiness + liveness probes to `/healthz` and gave
  them a 3s timeout (`infra/k8s/base/web.yaml`). Deployed as
  `tracker-web:20260625-healthz`.
- **Frontend source files untracked by git**: the Python `lib/` ignore rule
  also matched `web/src/lib/`, so `accounts.ts`, `format.ts`, `portfolio.ts`,
  and `utils.ts` were never committed and a fresh clone could not build the
  web app. Added a `.gitignore` negation and committed the files; added
  `web/public/.gitkeep` so the (empty) public dir exists in clones.
- **Congressional disclosure detail 404**: clicking "Details" on a disclosure
  returned a 404. Next.js delivers the dynamic `[filingId]` segment
  still percent-encoded and the openapi-fetch client re-encoded it, so
  synthetic IDs containing a colon (`quiver-filing:<digest>`) were
  double-encoded (`%253A`) and the API returned 404 → `notFound()`. Fixed by
  decoding the route param once before the API call
  (`web/src/app/congressional/[filingId]/page.tsx`). Deployed as web image
  `tracker-web:20260623-1`.
