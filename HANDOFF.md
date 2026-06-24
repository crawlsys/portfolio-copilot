# Operations Runbook

Operational notes for running Tracker on Kubernetes. Replace placeholder
hostnames/registries (`example.com`, `registry.example.com`) with your own.

> No personal financial data, account numbers, or infrastructure identifiers
> belong in this file. Account data lives only in `data/holdings*.json`
> (git-ignored) and the cluster database/secrets.

## Services

| Component | Purpose |
|-----------|---------|
| api | FastAPI (`:8001`) — portfolio, congressional, digest endpoints |
| worker | Continuous outbox-relay loop (scheduler disabled: `WORKER_SCHEDULE=false`) |
| web | Next.js dashboard (`:3001`) |
| postgres | Database |

## Scheduled jobs — k8s CronJobs (`infra/k8s/base/cronjobs.yaml`)

Scheduled work runs as native CronJobs (timezone `America/New_York`), each
invoking `python -m apps.worker.run_job <job_id>` (`apps/worker/run_job.py`).
One pod per run, native history/retries; a missed run is visible
(`kubectl get cronjobs`) instead of silently lost.

| Job | Schedule (ET) |
|-----|---------------|
| daily digest | `0 7 * * *` |
| congressional ingest (market) | `0 9-16 * * 1-5` |
| congressional ingest (off-hours) | `0 0,4,8,20 * * *` |
| token canary | `0,30 9-16 * * 1-5` |
| pipeline health | `0 * * * *` |
| VIX alert | `0,30 9-16 * * 1-5` |

Trigger one ad-hoc: `kubectl create job --from=cronjob/<name> adhoc -n <ns>`.

## Holdings (ConfigMap-mounted)

Positions live in `data/holdings*.json`, mounted via a ConfigMap (not baked into
the image). Update after a fill:

```bash
kubectl create configmap tracker-holdings -n <ns> \
  --from-file=holdings.json=data/holdings.json \
  --from-file=holdings-individual.json=data/holdings-individual.json \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deploy/<api> deploy/<worker> -n <ns>
curl -X POST https://<api-host>/portfolio/<account_id>/refresh
```

Each file models one account (`account_id`, `cash`, `managed`, `holdings[]`).
Mark advisor/managed accounts `"managed": true` → hold-only in recommendations.

## Deploy a change

```bash
docker build -f docker/backend.Dockerfile -t registry.example.com/tracker-backend:<tag> .
docker push registry.example.com/tracker-backend:<tag>
kubectl set image deploy/<api> api=registry.example.com/tracker-backend:<tag> -n <ns>
kubectl set image deploy/<worker> worker=... -n <ns>
# also re-pin the CronJob images: kubectl set image cronjob/<name> job=<tag> -n <ns>
kubectl rollout status deploy/<api> -n <ns>
```

## Known gotchas

- The market-data snapshot endpoint returns `last=0` outside market hours; the
  quote layer falls back to previous-close so the live total reconciles 24/7.
- CUSIP-identified instruments (treasuries) aren't equity tickers; `coerce_symbol`
  keeps them instead of dropping them — a regression test guards this.
- Instruments the market-data provider can't quote (funds, preferreds, illiquid
  OTC) retain their last-known value on live refresh rather than zeroing.
- Jobs log via stdlib `logging`; the CronJob dispatcher configures a handler so
  job output (including push results) is visible in pod logs.
- Ingress: each public hostname needs an explicit route at your tunnel/ingress
  layer; a wildcard that points at an ingress controller with no matching route
  will 404.

## Open / pending

- **Live broker adapter** — swap the file-backed `fake` broker for the live
  brokerage API to reconcile all accounts automatically.
- **Backtest harness** — future phase.
