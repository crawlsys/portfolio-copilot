"""Notification adapter contracts and the default logging implementation."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CriticalAlert:
    """The operational event that is allowed to page the user."""

    name: str
    summary: str
    details: Mapping[str, object]
    occurred_at: datetime
    event_type: str = "ops.critical_alert.v1"


class NotifierPort(Protocol):
    """Critical alert delivery boundary.

    The v1 implementation logs only. Push/SMS integration plugs in behind
    this shape later without changing the canaries or handlers.
    """

    def send_critical_alert(self, alert: CriticalAlert) -> None: ...


class LoggingNotifier:
    """Notifier that emits critical alerts to the process log."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(__name__)

    def send_critical_alert(self, alert: CriticalAlert) -> None:
        self._logger.critical(
            "%s: %s",
            alert.name,
            alert.summary,
            extra={
                "event_type": alert.event_type,
                "alert_name": alert.name,
                "details": dict(alert.details),
                "occurred_at": alert.occurred_at.isoformat(),
            },
        )


__all__ = ["CriticalAlert", "LoggingNotifier", "NotifierPort"]
