"""VIX alert job — fires Pushover when VIX crosses key thresholds.

Two alerts:
- VIX < 18: "BUY WINDOW" — market is calm, good time to deploy cash
- VIX > 28: "RISK OFF" — market is panicking, be cautious

Runs every 30 minutes during market hours.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from apps.common.settings import get_settings
from trading.domain import Severity

_log = logging.getLogger(__name__)

BUY_WINDOW_THRESHOLD = Decimal("18")
RISK_OFF_THRESHOLD = Decimal("28")


async def run_vix_check() -> None:
    """Check VIX and push alert if threshold crossed."""
    settings = get_settings()
    if not settings.massive_api_key:
        return

    from trading.adapters.massive.client import MassiveClient  # noqa: PLC0415

    client = MassiveClient(api_key=settings.massive_api_key)
    try:
        vix = await client.get_vix()
        if vix == Decimal("0"):
            return

        _log.info("VIX check: %s", vix)

        if settings.push_provider == "pushover" and settings.pushover_api_token:
            from trading.adapters.notifications.pushover import PushoverNotifier  # noqa: PLC0415

            notifier = PushoverNotifier(
                api_token=settings.pushover_api_token,
                user_key=settings.pushover_user_key,
            )

            if vix < BUY_WINDOW_THRESHOLD:
                await notifier.send(
                    title="🟢 VIX Buy Window",
                    body=f"VIX at {vix} — below 18. Market is calm. Consider deploying cash tranches.",
                    severity=Severity.INFO,
                    tags=["vix", "buy-signal"],
                )
                _log.info("VIX buy-window alert sent (%s)", vix)
            elif vix > RISK_OFF_THRESHOLD:
                await notifier.send(
                    title="🔴 VIX Risk-Off",
                    body=f"VIX at {vix} — above 28. Elevated fear. Hold off on new buys.",
                    severity=Severity.WARNING,
                    tags=["vix", "risk-off"],
                )
                _log.info("VIX risk-off alert sent (%s)", vix)

            await notifier.aclose()
    finally:
        await client.aclose()


def run_vix_check_sync() -> None:
    asyncio.run(run_vix_check())
