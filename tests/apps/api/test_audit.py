"""Audit route tests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import apps.api.routes.audit as audit_route
from apps.api.app import create_app
from fastapi.testclient import TestClient


@dataclass(frozen=True, slots=True)
class _AuditSeed:
    id: int
    audit_id: str
    event_type: str
    actor: str | None
    action: str
    subject_type: str
    subject_id: str
    occurred_at: datetime
    correlation_id: str | None
    metadata: dict[str, str]


class _FakeResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeResult:
        return self

    def all(self) -> list[Mapping[str, object]]:
        return self._rows


class _FakeAuditSession:
    def __init__(self, seeds: list[_AuditSeed]) -> None:
        self._seeds = seeds

    async def __aenter__(self) -> _FakeAuditSession:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def execute(self, statement: object, params: dict[str, object]) -> _FakeResult:
        del statement
        if "correlation_id" in params:
            rows = [r for r in self._seeds if r.correlation_id == params["correlation_id"]]
        else:
            rows = [
                r
                for r in self._seeds
                if r.subject_type == params["subject_type"] and r.subject_id == params["subject_id"]
            ]
        rows.sort(key=lambda r: (r.occurred_at, r.id))
        return _FakeResult(
            [
                {
                    "audit_id": r.audit_id,
                    "event_type": r.event_type,
                    "actor": r.actor,
                    "action": r.action,
                    "subject_type": r.subject_type,
                    "subject_id": r.subject_id,
                    "occurred_at": r.occurred_at,
                    "correlation_id": r.correlation_id,
                    "metadata": r.metadata,
                }
                for r in rows
            ]
        )


def _seeded_client(monkeypatch: Any) -> TestClient:
    now = datetime(2026, 6, 21, 14, 0, tzinfo=UTC)
    seeds = [
        _AuditSeed(
            id=2,
            audit_id="audit-2",
            event_type="portfolio.position_reconciled.v1",
            actor="worker",
            action="reconciled",
            subject_type="position",
            subject_id="acct:AAPL",
            occurred_at=now + timedelta(minutes=1),
            correlation_id="corr-1",
            metadata={"symbol": "AAPL"},
        ),
        _AuditSeed(
            id=1,
            audit_id="audit-1",
            event_type="portfolio.position_drift_detected.v1",
            actor="worker",
            action="drift_detected",
            subject_type="position",
            subject_id="acct:AAPL",
            occurred_at=now,
            correlation_id="corr-1",
            metadata={"severity": "CRITICAL"},
        ),
        _AuditSeed(
            id=3,
            audit_id="audit-3",
            event_type="signals.signal_produced.v1",
            actor="worker",
            action="produced",
            subject_type="signal",
            subject_id="sig-1",
            occurred_at=now,
            correlation_id="corr-2",
            metadata={},
        ),
    ]

    monkeypatch.setattr(audit_route, "session_factory", lambda comp: _FakeAuditSession(seeds))

    app = create_app()
    client = TestClient(app)
    client.app.state.composition = SimpleNamespace(engine=object())
    return client


def test_audit_chain_returns_chronological_events(monkeypatch: Any) -> None:
    client = _seeded_client(monkeypatch)

    response = client.get("/audit/chain/corr-1")

    assert response.status_code == 200
    body = response.json()
    assert body["correlation_id"] == "corr-1"
    assert [event["audit_id"] for event in body["events"]] == ["audit-1", "audit-2"]
    assert body["events"][0]["actor"] == "worker"
    assert body["events"][0]["action"] == "drift_detected"
    assert body["events"][0]["timestamp"] == "2026-06-21T14:00:00+00:00"


def test_audit_subject_returns_subject_records(monkeypatch: Any) -> None:
    client = _seeded_client(monkeypatch)

    response = client.get("/audit/subject/position/acct:AAPL")

    assert response.status_code == 200
    body = response.json()
    assert body["subject_type"] == "position"
    assert body["subject_id"] == "acct:AAPL"
    assert [event["audit_id"] for event in body["events"]] == ["audit-1", "audit-2"]
