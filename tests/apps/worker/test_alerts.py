"""Worker alert tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from apps.worker.handlers.drift_alert import handle_position_drift_alert
from apps.worker.jobs.pipeline_health import run_pipeline_health
from apps.worker.jobs.token_canary import run_token_canary

from trading.adapters.notifications import CriticalAlert
from trading.application.common.event_envelope import EventEnvelope
from trading.domain import AggregateType, EventType


class _Clock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class _Notifier:
    def __init__(self) -> None:
        self.alerts: list[CriticalAlert] = []

    def send_critical_alert(self, alert: CriticalAlert) -> None:
        self.alerts.append(alert)


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
    assert [alert.name for alert in notifier.alerts] == ["schwab_auth_unhealthy"]


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

    assert [alert.name for alert in notifier.alerts] == ["position_drift_critical"]
    assert notifier.alerts[0].details["symbol"] == "AAPL"


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
    assert [alert.name for alert in notifier.alerts] == ["data_pipeline_stalled"]
