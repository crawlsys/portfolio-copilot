"""Data pipeline health canary."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from trading.adapters.notifications import NotifierPort
from trading.application.common.clock import ClockPort
from trading.domain import Severity

CONGRESSIONAL_STALE_AFTER = timedelta(hours=48)
MARKET_DATA_STALE_AFTER = timedelta(minutes=30)
MARKET_TIMEZONE = ZoneInfo("America/New_York")


class SchedulerLike(Protocol):
    def add_job(
        self, job: Callable[..., object] | object, trigger: str, **kwargs: object
    ) -> object: ...


async def run_pipeline_health(
    *,
    session: AsyncSession,
    notifier: NotifierPort,
    clock: ClockPort,
) -> bool:
    """Return True when source data is fresh; alert and return False on stalls."""
    now = clock.now()
    last_disclosure = await _last_timestamp(
        session, "SELECT max(disclosure_date) FROM trade_disclosures"
    )
    last_market_update = await _last_timestamp(session, "SELECT max(updated_at) FROM quote_cache")

    stalled: dict[str, object] = {}
    if (
        last_disclosure is None
        or now - _coerce_timezone(last_disclosure, now) > CONGRESSIONAL_STALE_AFTER
    ):
        stalled["last_congressional_disclosure"] = (
            last_disclosure.isoformat() if last_disclosure else None
        )

    if _is_market_hours(now) and (
        last_market_update is None
        or now - _coerce_timezone(last_market_update, now) > MARKET_DATA_STALE_AFTER
    ):
        stalled["last_market_data_update"] = (
            last_market_update.isoformat() if last_market_update else None
        )

    if not stalled:
        return True

    await notifier.send(
        "Source data has stopped flowing",
        f"Data pipeline stalled at {now.isoformat()}: {stalled}",
        severity=Severity.WARNING,
        tags=["pipeline", "stale-data"],
    )
    return False


def schedule_pipeline_health(
    scheduler: SchedulerLike,
    *,
    job: Callable[..., object] | object,
) -> None:
    """Register a caller-provided pipeline health job with APScheduler."""
    scheduler.add_job(
        job,
        "cron",
        day_of_week="mon-fri",
        minute="*/30",
        timezone=str(MARKET_TIMEZONE),
        id="data_pipeline_stalled",
        replace_existing=True,
    )


async def _last_timestamp(session: AsyncSession, query: str) -> datetime | None:
    value = await session.scalar(text(query))
    if value is None or isinstance(value, datetime):
        return value
    raise TypeError(f"Expected datetime or None from health query, got {type(value).__name__}")


def _is_market_hours(now: datetime) -> bool:
    local_now = now.astimezone(MARKET_TIMEZONE)
    if local_now.weekday() >= 5:
        return False
    return time(hour=9, minute=30) <= local_now.time() <= time(hour=16)


def _coerce_timezone(value: datetime, reference: datetime) -> datetime:
    if value.tzinfo is not None:
        return value
    return value.replace(tzinfo=reference.tzinfo)


__all__ = [
    "CONGRESSIONAL_STALE_AFTER",
    "MARKET_DATA_STALE_AFTER",
    "run_pipeline_health",
    "schedule_pipeline_health",
]
