"""Single-job entrypoint for k8s CronJobs.

Usage: ``python -m apps.worker.run_job <job_id>``

Each job that used to fire via the in-process APScheduler now runs as a discrete
k8s CronJob invoking this dispatcher (one pod per run, native history/retries).
The ``tracker-worker`` Deployment keeps running only the continuous outbox-relay
loop, with ``WORKER_SCHEDULE=false`` so the in-process scheduler stays off and
jobs don't double-fire.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

import structlog

log = structlog.get_logger()


def _briefing() -> None:
    from apps.worker.jobs.generate_briefing import run_briefing_sync

    run_briefing_sync()


def _digest() -> None:
    from apps.worker.jobs.generate_digest_job import run_digest_sync

    run_digest_sync()


def _ingest() -> None:
    from apps.worker.jobs.ingest_congressional import run_ingest_sync

    run_ingest_sync()


def _token_canary() -> None:
    from apps.worker.jobs.token_canary_runner import run_token_canary_sync

    run_token_canary_sync()


def _pipeline_health() -> None:
    from apps.worker.jobs.pipeline_health_runner import run_pipeline_health_sync

    run_pipeline_health_sync()


def _vix_alert() -> None:
    from apps.worker.jobs.vix_alert import run_vix_check_sync

    run_vix_check_sync()


# job_id -> runner. job_ids match the APScheduler job ids they replace.
JOBS: dict[str, Callable[[], None]] = {
    "daily_briefing": _briefing,
    "daily_digest": _digest,
    "congressional_ingest": _ingest,
    "token_canary": _token_canary,
    "pipeline_health": _pipeline_health,
    "vix_alert": _vix_alert,
}


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1 or args[0] not in JOBS:
        valid = ", ".join(sorted(JOBS))
        print(f"usage: python -m apps.worker.run_job <job_id>\n  job_id one of: {valid}")
        return 2

    import logging

    from apps.worker.__main__ import _setup_logging

    _setup_logging()
    # Several jobs (e.g. the briefing) log via the stdlib logging module, which
    # has no handler unless we add one — without this their output (including
    # "briefing pushed via Pushover" and Pushover send failures, which are
    # logged-not-raised) is silently dropped in the CronJob pod.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    job_id = args[0]
    log.info("cronjob_start", job=job_id)
    JOBS[job_id]()
    log.info("cronjob_done", job=job_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
