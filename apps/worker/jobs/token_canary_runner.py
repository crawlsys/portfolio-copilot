"""Sync runner for token_canary job.

Wraps the async run_token_canary with dependency injection for the scheduler.
"""

from __future__ import annotations

import asyncio
import logging

from apps.common.settings import get_settings
from trading.adapters.notifications import LoggingNotifier
from trading.application.common.clock import SystemClock

_log = logging.getLogger(__name__)


def run_token_canary_sync() -> None:
    """Sync wrapper for APScheduler."""
    asyncio.run(_run_token_canary())


async def _run_token_canary() -> None:
    """Run the token canary check with injected dependencies."""
    settings = get_settings()

    if settings.broker_mode != "schwab" or not settings.schwab_client_id:
        _log.debug("Schwab broker not configured — skipping token canary")
        return

    try:
        from trading.adapters.schwab.broker import SchwabBrokerAdapter  # noqa: PLC0415

        broker = SchwabBrokerAdapter(
            client_id=settings.schwab_client_id,
            client_secret=settings.schwab_client_secret,
            redirect_uri=settings.schwab_redirect_uri,
        )
    except Exception:
        _log.warning(
            "Failed to construct SchwabBrokerAdapter — skipping token canary", exc_info=True
        )
        return

    notifier = _get_notifier(settings)
    clock = SystemClock()

    from apps.worker.jobs.token_canary import run_token_canary  # noqa: PLC0415

    try:
        healthy = await run_token_canary(
            broker=broker,
            notifier=notifier,
            clock=clock,
            token_expires_at=None,
        )
        if healthy:
            _log.info("Token canary: healthy")
        else:
            _log.warning("Token canary: UNHEALTHY — notification sent")
    except Exception:
        _log.exception("Token canary failed with exception")


def _get_notifier(settings: object) -> LoggingNotifier:
    """Get a notifier based on settings. Returns LoggingNotifier as default."""
    # TODO: wire up NtfyNotifier when push_provider is set
    return LoggingNotifier()
