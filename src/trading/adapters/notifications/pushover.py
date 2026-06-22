"""Pushover push notification adapter.

POSTs to https://api.pushover.net/1/messages.json. Uses the user's existing
Pushover credentials (same ones used by usage-monitor + other homelab services).
"""

from __future__ import annotations

import logging

import httpx

from trading.adapters.notifications.protocol import CriticalAlert
from trading.domain import Severity

_log = logging.getLogger(__name__)

PUSHOVER_URL = "https://api.pushover.net/1/messages.json"

# Map our Severity to Pushover priority (-2 to 2)
_SEVERITY_TO_PRIORITY = {
    Severity.INFO: "-1",  # quiet notification
    Severity.WARNING: "0",  # normal
    Severity.CRITICAL: "1",  # high-priority, bypasses quiet hours
    # Pushover emergency priority (2) requires retry/expire params; we use 1
    # for critical which is high-priority without the retry overhead.
}


class PushoverNotifier:
    """Pushes notifications via Pushover.net API.

    Uses the same Pushover app token + user key as the user's other homelab
    services. Credentials from .env: PUSHOVER_API_TOKEN + PUSHOVER_USER_KEY.
    """

    def __init__(
        self,
        api_token: str,
        user_key: str,
        device: str | None = None,
        sound: str = "pushover",
    ) -> None:
        if not api_token or not user_key:
            raise ValueError("PushoverNotifier requires api_token + user_key")
        self._api_token = api_token
        self._user_key = user_key
        self._device = device  # None = all devices
        self._sound = sound
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def send(
        self,
        title: str,
        body: str,
        severity: Severity = Severity.INFO,
        tags: list[str] | None = None,
        click_url: str | None = None,
    ) -> None:
        """Send a notification via Pushover. Failures are logged, not raised."""
        data: dict[str, str] = {
            "token": self._api_token,
            "user": self._user_key,
            "title": title[:256],
            "message": body[:1024],
            "priority": _SEVERITY_TO_PRIORITY.get(severity, "0"),
            "sound": self._sound,
        }
        if self._device:
            data["device"] = self._device
        if click_url:
            data["url"] = click_url
        if tags:
            # Pushover doesn't have tags; prepend to title as a compact prefix
            tag_str = " ".join(f"#{t}" for t in tags[:3])
            data["title"] = f"{tag_str} {data['title']}"[:256]

        try:
            client = await self._get_client()
            response = await client.post(PUSHOVER_URL, data=data)
            if response.status_code != 200:
                _log.warning(
                    "pushover send failed: HTTP %s — %s",
                    response.status_code,
                    response.text[:200],
                )
        except Exception as exc:  # noqa: BLE001
            _log.warning("pushover send error: %s", exc)

    async def send_critical(
        self,
        title: str,
        body: str,
        tags: list[str] | None = None,
        click_url: str | None = None,
    ) -> None:
        await self.send(title, body, severity=Severity.CRITICAL, tags=tags, click_url=click_url)

    async def send_critical_alert(self, alert: CriticalAlert) -> None:
        """Push a structured CriticalAlert at high priority."""
        body_lines = [alert.summary]
        for key, value in alert.details.items():
            body_lines.append(f"{key}: {value}")
        await self.send(
            title=f"🚨 {alert.name}",
            body="\n".join(body_lines)[:1024],
            severity=Severity.CRITICAL,
            tags=[alert.name],
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


__all__ = ["PushoverNotifier"]
