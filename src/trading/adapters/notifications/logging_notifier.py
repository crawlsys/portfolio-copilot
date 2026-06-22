"""Development fallback notifier."""

from __future__ import annotations

import json
import logging
import sys

from trading.adapters.notifications.protocol import CriticalAlert
from trading.domain import Severity


class LoggingNotifier:
    """Notifier that emits structured log records instead of pushing externally."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        if logger is None:
            logger = logging.getLogger(__name__)
            _ensure_stderr_handler(logger)
        self._logger = logger

    async def send(
        self,
        title: str,
        body: str,
        severity: Severity = Severity.INFO,
        tags: list[str] | None = None,
        click_url: str | None = None,
    ) -> None:
        level = _level_for_severity(severity)
        self._logger.log(
            level,
            "%s: %s",
            title,
            body,
            extra={
                "notification_title": title,
                "notification_body": body,
                "severity": severity.name,
                "tags": tags or [],
                "click_url": click_url,
            },
        )

    async def send_critical(
        self,
        title: str,
        body: str,
        tags: list[str] | None = None,
        click_url: str | None = None,
    ) -> None:
        self._logger.critical(
            "Critical notification requested",
            extra={"notification_title": title, "tags": tags or [], "click_url": click_url},
        )
        await self.send(title, body, severity=Severity.CRITICAL, tags=tags, click_url=click_url)

    async def send_critical_alert(self, alert: CriticalAlert) -> None:
        """Log a structured CriticalAlert."""
        body_lines = [alert.summary]
        for key, value in alert.details.items():
            body_lines.append(f"  {key}: {value}")
        self._logger.critical("ALERT [%s]: %s", alert.name, "\n".join(body_lines))


def _level_for_severity(severity: Severity) -> int:
    if severity is Severity.CRITICAL:
        return logging.CRITICAL
    if severity is Severity.WARNING:
        return logging.WARNING
    return logging.INFO


def _ensure_stderr_handler(logger: logging.Logger) -> None:
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("notification_title", "notification_body", "severity", "tags", "click_url"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, separators=(",", ":"))


__all__ = ["LoggingNotifier"]
