"""ntfy.sh notification adapter."""

from __future__ import annotations

import logging

import httpx

from trading.adapters.notifications.protocol import CriticalAlert
from trading.domain import Severity

_log = logging.getLogger(__name__)


class NtfyNotifier:
    """Push notifications through ntfy.sh or a self-hosted ntfy server."""

    def __init__(
        self,
        *,
        topic: str,
        server_url: str = "https://ntfy.sh",
        auth_token: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not topic.strip():
            raise ValueError("ntfy topic is required")
        self._server_url = server_url.rstrip("/")
        self._topic = topic.strip("/")
        self._auth_token = auth_token or None
        self._client = client
        self._owns_client = client is None

    async def send(
        self,
        title: str,
        body: str,
        severity: Severity = Severity.INFO,
        tags: list[str] | None = None,
        click_url: str | None = None,
    ) -> None:
        headers = {
            "Title": title,
            "Priority": _priority_for_severity(severity),
        }
        if tags:
            headers["Tags"] = ",".join(tags)
        if click_url:
            headers["Click"] = click_url
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"

        response = await self._get_client().post(
            f"{self._server_url}/{self._topic}",
            content=body.encode("utf-8"),
            headers=headers,
        )
        response.raise_for_status()

    async def send_critical(
        self,
        title: str,
        body: str,
        tags: list[str] | None = None,
        click_url: str | None = None,
    ) -> None:
        _log.critical(
            "Sending critical ntfy notification",
            extra={"notification_title": title, "tags": tags or [], "click_url": click_url},
        )
        await self.send(title, body, severity=Severity.CRITICAL, tags=tags, click_url=click_url)

    async def send_critical_alert(self, alert: CriticalAlert) -> None:
        """Push a structured CriticalAlert at high priority."""
        body_lines = [alert.summary]
        for key, value in alert.details.items():
            body_lines.append(f"  {key}: {value}")
        await self.send(
            title=f"🚨 {alert.name}",
            body="\n".join(body_lines),
            severity=Severity.CRITICAL,
            tags=["rotating_light", alert.name],
        )

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client


def _priority_for_severity(severity: Severity) -> str:
    if severity is Severity.CRITICAL:
        return "max"
    if severity is Severity.WARNING:
        return "high"
    return "default"


__all__ = ["NtfyNotifier"]
