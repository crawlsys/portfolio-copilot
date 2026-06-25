# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- **Web `/healthz` probe endpoint**: lightweight route returning 200 without
  calling the backend API, so pod readiness/liveness is decoupled from upstream
  latency (`web/src/app/healthz/route.ts`).

### Fixed
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
