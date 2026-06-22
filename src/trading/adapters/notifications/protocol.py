"""Notification adapter protocol + CriticalAlert dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from trading.domain import Severity


@dataclass(frozen=True, slots=True)
class CriticalAlert:
    """Structured critical alert. Only 3 types exist in the system
    (per spec §Observability — schwab_auth_unhealthy, position_drift_critical,
    data_pipeline_stalled)."""

    name: str
    summary: str
    details: dict[str, str] = field(default_factory=dict)
    severity: Severity = Severity.CRITICAL


@runtime_checkable
class NotifierPort(Protocol):
    """Boundary for push-style operational notifications."""

    async def send(
        self,
        title: str,
        body: str,
        severity: Severity = Severity.INFO,
        tags: list[str] | None = None,
        click_url: str | None = None,
    ) -> None: ...

    async def send_critical_alert(self, alert: CriticalAlert) -> None: ...

    async def send_critical(
        self,
        title: str,
        body: str,
        tags: list[str] | None = None,
        click_url: str | None = None,
    ) -> None: ...


__all__ = ["CriticalAlert", "NotifierPort"]
