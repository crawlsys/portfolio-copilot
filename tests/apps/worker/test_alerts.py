"""Worker alert tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from apps.worker.handlers.drift_alert import handle_position_drift_alert
from apps.worker.jobs.pipeline_health import run_pipeline_health
from apps.worker.jobs.token_canary import run_token_canary

from trading.application.common.event_envelope import EventEnvelope
from trading.domain import AggregateType, EventType, Severity


class _Clock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class _Notifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, Severity, list[str] | None, str | None]] = []
        self.critical: list[tuple[str, str, list[str] | None, str | None]] = []

    async def send(
        self,
        title: str,
        body: str,
        severity: Severity = Severity.INFO,
        tags: list[str] | None = None,
        click_url: str | None = None,
    ) -> None:
        self.sent.append((title, body, severity, tags, click_url))

    async def send_critical(
        self,
        title: str,
        body: str,
        tags: list[str] | None = None,
        click_url: str | None = None,
    ) -> None:
        self.critical.append((title, body, tags, click_url))


class _FailingBroker:
    async def get_accounts(self) -> tuple[object, ...]:
        raise RuntimeError("bad token")


class _FakePipelineSession:
    def __init__(self, values: list[datetime | None]) -> None:
        self._values = values

    async def scalar(self, statement: object) -> datetime | None:
        del statement
        return self._values.pop(0)


@pytest.mark.asyncio
async def test_token_canary_alerts_on_auth_failure() -> None:
    notifier = _Notifier()

    healthy = await run_token_canary(
        broker=_FailingBroker(),
        notifier=notifier,
        clock=_Clock(datetime(2026, 6, 21, 14, 0, tzinfo=UTC)),
    )

    assert healthy is False
    assert [call[0] for call in notifier.critical] == ["Schwab account canary failed"]


def test_drift_alert_fires_for_critical_drift() -> None:
    notifier = _Notifier()
    now = datetime(2026, 6, 21, 14, 0, tzinfo=UTC)
    envelope = EventEnvelope(
        id=uuid4(),
        type=EventType.POSITION_DRIFT_DETECTED,
        aggregate_id="acct:AAPL",
        aggregate_type=AggregateType.POSITION,
        occurred_at=now,
        correlation_id=uuid4(),
        payload={
            "account_id": "acct",
            "symbol": "AAPL",
            "drift_kind": "MISSING_BROKER",
            "severity": "CRITICAL",
        },
    )

    handle_position_drift_alert(envelope, object(), notifier=notifier, clock=_Clock(now))

    assert [call[0] for call in notifier.critical] == ["Critical broker position drift detected"]
    assert "AAPL" in notifier.critical[0][1]


@pytest.mark.asyncio
async def test_pipeline_health_alerts_on_stale_data() -> None:
    notifier = _Notifier()
    now = datetime(2026, 6, 22, 15, 0, tzinfo=UTC)
    session = _FakePipelineSession(
        [
            now - timedelta(days=3),
            now - timedelta(hours=2),
        ]
    )

    healthy = await run_pipeline_health(
        session=session,
        notifier=notifier,
        clock=_Clock(now),
    )

    assert healthy is False
    assert [call[0] for call in notifier.sent] == ["Source data has stopped flowing"]
    assert notifier.sent[0][2] is Severity.WARNING
