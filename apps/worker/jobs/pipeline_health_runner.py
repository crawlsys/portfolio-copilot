"""Sync runner for pipeline_health job.

Wraps the async run_pipeline_health with dependency injection for the scheduler.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.pool import NullPool

from apps.common.settings import get_settings
from trading.adapters.notifications import LoggingNotifier
from trading.application.common.clock import SystemClock

_log = logging.getLogger(__name__)


def run_pipeline_health_sync() -> None:
    """Sync wrapper for APScheduler."""
    asyncio.run(_run_pipeline_health())


async def _run_pipeline_health() -> None:
    """Run the pipeline health check with injected dependencies."""
    settings = get_settings()

    if not settings.database_url:
        _log.warning("DATABASE_URL not set — skipping pipeline health check")
        return

    try:
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: PLC0415

        async_url = settings.database_url
        if "+psycopg_async" not in async_url:
            async_url = async_url.replace("+psycopg", "+psycopg_async")
            if "+psycopg_async" not in async_url:
                async_url = async_url.replace("postgresql://", "postgresql+psycopg_async://")

        async_engine = create_async_engine(async_url, poolclass=NullPool)

        notifier = _get_notifier(settings)
        clock = SystemClock()

        from apps.worker.jobs.pipeline_health import run_pipeline_health  # noqa: PLC0415

        async with AsyncSession(async_engine, expire_on_commit=False) as session:
            healthy = await run_pipeline_health(
                session=session,
                notifier=notifier,
                clock=clock,
            )
            if healthy:
                _log.info("Pipeline health: all sources fresh")
            else:
                _log.warning("Pipeline health: stale data detected — notification sent")

        await async_engine.dispose()
    except Exception:
        _log.exception("Pipeline health check failed")


def _get_notifier(settings: object) -> LoggingNotifier:
    """Get a notifier based on settings. Returns LoggingNotifier as default."""
    # TODO: wire up NtfyNotifier when push_provider is set
    return LoggingNotifier()
