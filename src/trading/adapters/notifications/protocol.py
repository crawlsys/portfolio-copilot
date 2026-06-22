"""Notification adapter protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from trading.domain import Severity


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

    async def send_critical(
        self,
        title: str,
        body: str,
        tags: list[str] | None = None,
        click_url: str | None = None,
    ) -> None: ...


__all__ = ["NotifierPort"]
