"""Critical position drift alert handler."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from trading.adapters.notifications import CriticalAlert, NotifierPort
from trading.application.common.event_envelope import EventEnvelope
from trading.domain import EventType

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from trading.application.common.clock import ClockPort
    from trading.application.common.event_bus import EventBus


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

    notifier.send_critical_alert(
        CriticalAlert(
            name="position_drift_critical",
            summary="Critical broker position drift detected",
            details={
                "event_id": str(envelope.id),
                "aggregate_id": envelope.aggregate_id,
                "account_id": envelope.payload.get("account_id"),
                "symbol": envelope.payload.get("symbol"),
                "drift_kind": envelope.payload.get("drift_kind"),
                "correlation_id": str(envelope.correlation_id),
            },
            occurred_at=clock.now(),
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


__all__ = [
    "handle_position_drift_alert",
    "make_position_drift_alert_handler",
    "subscribe_drift_alert",
]
