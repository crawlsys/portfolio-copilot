"""APScheduler-based worker process.

Runs scheduled jobs:
- Congressional ingest: hourly during market hours, every 4h otherwise
- Daily briefing: 7 AM ET
- Token canary: every 30 minutes during market hours
- Pipeline health: every hour

Plus a continuous outbox relay loop that promotes events from outbox to event_log.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

if TYPE_CHECKING:
    from apscheduler.schedulers.base import BaseScheduler

MARKET_TIMEZONE = "America/New_York"


def create_worker(*, start: bool = False) -> BackgroundScheduler:
    """Build the scheduler with all jobs registered.

    Args:
        start: If True, starts the scheduler immediately. Default False for testing.

    Returns:
        Configured BackgroundScheduler instance.

    Environment:
        WORKER_SCHEDULE: If "false", skips job registration (for testing composition).
    """
    scheduler = BackgroundScheduler(timezone=MARKET_TIMEZONE)

    if os.getenv("WORKER_SCHEDULE", "true").lower() != "false":
        _register_jobs(scheduler)

    if start:
        scheduler.start()

    return scheduler


def _register_jobs(scheduler: BaseScheduler) -> None:
    """Register all scheduled jobs."""
    from apps.worker.jobs.generate_briefing import run_briefing_sync  # noqa: PLC0415
    from apps.worker.jobs.ingest_congressional import run_ingest_sync  # noqa: PLC0415

    # Congressional ingest: hourly during market hours (9:30-16:00 ET weekdays)
    scheduler.add_job(
        run_ingest_sync,
        CronTrigger(
            day_of_week="mon-fri",
            hour="9-16",
            minute=0,
            timezone=MARKET_TIMEZONE,
        ),
        id="congressional_ingest_market_hours",
        replace_existing=True,
    )

    # Congressional ingest: every 4 hours outside market hours
    scheduler.add_job(
        run_ingest_sync,
        CronTrigger(
            hour="0,4,8,20",
            minute=0,
            timezone=MARKET_TIMEZONE,
        ),
        id="congressional_ingest_off_hours",
        replace_existing=True,
    )

    # Daily briefing: 7 AM ET
    scheduler.add_job(
        run_briefing_sync,
        CronTrigger(
            hour=7,
            minute=0,
            timezone=MARKET_TIMEZONE,
        ),
        id="daily_briefing",
        replace_existing=True,
    )

    # Token canary and pipeline health use their own scheduling helpers.
    # They require broker/notifier/session — we pass stubs here and let the
    # jobs themselves handle construction. For now, schedule wrapper jobs.
    _register_canary_job(scheduler)
    _register_pipeline_health_job(scheduler)
    _register_vix_job(scheduler)


def _register_canary_job(scheduler: BaseScheduler) -> None:
    """Register token canary with a sync wrapper."""
    from apps.worker.jobs.token_canary_runner import run_token_canary_sync  # noqa: PLC0415

    # Every 30 minutes during market hours (9-16 ET weekdays)
    scheduler.add_job(
        run_token_canary_sync,
        CronTrigger(
            day_of_week="mon-fri",
            hour="9-16",
            minute="0,30",
            timezone=MARKET_TIMEZONE,
        ),
        id="token_canary_market_hours",
        replace_existing=True,
    )


def _register_pipeline_health_job(scheduler: BaseScheduler) -> None:
    """Register pipeline health with a sync wrapper."""
    from apps.worker.jobs.pipeline_health_runner import run_pipeline_health_sync  # noqa: PLC0415

    # Every hour
    scheduler.add_job(
        run_pipeline_health_sync,
        IntervalTrigger(hours=1),
        id="pipeline_health",
        replace_existing=True,
    )


def _register_vix_job(scheduler: BaseScheduler) -> None:
    """Register VIX threshold alert (every 30 min during market hours)."""
    from apps.worker.jobs.vix_alert import run_vix_check_sync  # noqa: PLC0415

    scheduler.add_job(
        run_vix_check_sync,
        CronTrigger(
            day_of_week="mon-fri",
            hour="9-16",
            minute="0,30",
            timezone=MARKET_TIMEZONE,
        ),
        id="vix_alert",
        name="vix_threshold_alert",
        replace_existing=True,
    )


__all__ = ["create_worker", "MARKET_TIMEZONE"]
