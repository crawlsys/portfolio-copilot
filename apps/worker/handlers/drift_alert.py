"""Critical position drift alert handler."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from trading.adapters.notifications import NotifierPort
from trading.application.common.event_envelope import EventEnvelope
from trading.domain import EventType

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from trading.application.common.clock import ClockPort
    from trading.application.common.event_bus import EventBus

_log = logging.getLogger(__name__)


def handle_position_drift_alert(
    envelope: EventEnvelope,
    _session: Session,
    *,
    notifier: NotifierPort,
    clock: ClockPort,
) -> None:
    """Page only for CRITICAL PositionDriftDetected events."""
    if envelope.type is not EventType.POSITION_DRIFT_DETECTED:
        return

    severity = envelope.payload.get("severity")
    if severity != "CRITICAL":
        return

    symbol = envelope.payload.get("symbol")
    account_id = envelope.payload.get("account_id")
    drift_kind = envelope.payload.get("drift_kind")
    _run_notification(
        notifier.send_critical(
            "Critical broker position drift detected",
            (
                f"Position drift detected for {symbol} in {account_id}. "
                f"Kind: {drift_kind}. Event: {envelope.id}. "
                f"Correlation: {envelope.correlation_id}. At: {clock.now().isoformat()}."
            ),
            tags=["portfolio", "drift", "critical"],
        )
    )


def make_position_drift_alert_handler(
    notifier: NotifierPort,
    clock: ClockPort,
) -> Callable[[EventEnvelope, Session], None]:
    def _handler(envelope: EventEnvelope, session: Session) -> None:
        handle_position_drift_alert(envelope, session, notifier=notifier, clock=clock)

    return _handler


def subscribe_drift_alert(
    bus: EventBus,
    *,
    notifier: NotifierPort,
    clock: ClockPort,
) -> None:
    bus.subscribe_sync(
        EventType.POSITION_DRIFT_DETECTED,
        make_position_drift_alert_handler(notifier, clock),
    )


def _run_notification(coro: Coroutine[Any, Any, None]) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro)
        return

    task = loop.create_task(coro)
    task.add_done_callback(_log_notification_failure)


def _log_notification_failure(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except Exception:  # noqa: BLE001 - notification failures should be visible in logs.
        _log.exception("Position drift notification failed")


__all__ = [
    "handle_position_drift_alert",
    "make_position_drift_alert_handler",
    "subscribe_drift_alert",
]
