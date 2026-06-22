"""Schwab auth canary.

This is one of three paging alerts. It performs only a read-only broker call.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Protocol

from trading.adapters.notifications import NotifierPort
from trading.adapters.ports.broker import BrokerPort
from trading.application.common.clock import ClockPort

TOKEN_TTL_ALERT_THRESHOLD = timedelta(hours=24)
MARKET_TIMEZONE = "America/New_York"


class SchedulerLike(Protocol):
    def add_job(
        self,
        func: Callable[..., Awaitable[bool]],
        trigger: str,
        **kwargs: object,
    ) -> object: ...


async def run_token_canary(
    *,
    broker: BrokerPort,
    notifier: NotifierPort,
    clock: ClockPort,
    token_expires_at: datetime | None = None,
) -> bool:
    """Return True when Schwab auth is healthy; alert and return False otherwise."""
    now = clock.now()
    try:
        await broker.get_accounts()
    except Exception as exc:  # noqa: BLE001 - adapter failures all mean auth canary failed.
        await notifier.send_critical(
            "Schwab account canary failed",
            f"Schwab auth canary failed at {now.isoformat()}: {exc!r}",
            tags=["schwab", "auth", "critical"],
        )
        return False

    if token_expires_at is not None:
        ttl = token_expires_at - now
        if ttl < TOKEN_TTL_ALERT_THRESHOLD:
            await notifier.send_critical(
                "Schwab refresh token expires soon",
                (
                    "Schwab refresh token expires in less than 24 hours. "
                    f"Expires at {token_expires_at.isoformat()}; "
                    f"ttl_seconds={int(ttl.total_seconds())}."
                ),
                tags=["schwab", "auth", "critical"],
            )
            return False

    return True


def schedule_token_canary(
    scheduler: SchedulerLike,
    *,
    broker: BrokerPort,
    notifier: NotifierPort,
    clock: ClockPort,
    token_expires_at: datetime | None = None,
) -> None:
    """Schedule the market-morning and market-hours auth canaries."""
    kwargs = {
        "broker": broker,
        "notifier": notifier,
        "clock": clock,
        "token_expires_at": token_expires_at,
    }
    scheduler.add_job(
        run_token_canary,
        "cron",
        day_of_week="mon-fri",
        hour=8,
        minute=0,
        timezone=MARKET_TIMEZONE,
        kwargs=kwargs,
        id="schwab_auth_unhealthy_morning",
        replace_existing=True,
    )
    scheduler.add_job(
        run_token_canary,
        "cron",
        day_of_week="mon-fri",
        hour="9-15",
        minute="*/30",
        timezone=MARKET_TIMEZONE,
        kwargs=kwargs,
        id="schwab_auth_unhealthy_market_hours",
        replace_existing=True,
    )


__all__ = ["run_token_canary", "schedule_token_canary", "TOKEN_TTL_ALERT_THRESHOLD"]
