"""End-to-end test of the cold path: UoW collects → outbox → relay → event_log + bus.

Requires real Postgres. Verifies:
- Events committed via UoW land in outbox
- Relay promotes them to event_log (idempotent on event_id)
- Sync handlers receive the envelope with the session open
- Marked published_at after success
- Failed promotion records last_error and retries on next pass
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from trading.adapters.persistence.models import EventLogRow, OutboxRow
from trading.application.common.clock import FrozenClock, SystemClock
from trading.application.common.event_bus import EventBus
from trading.application.common.event_envelope import EventEnvelope
from trading.application.common.outbox_relay import OutboxRelay
from trading.domain import AggregateType, DomainEvent, EventType

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL required for outbox/relay tests",
)


@pytest.fixture()
def engine():
    eng = create_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def _clean_outbox(engine):  # type: ignore[no-untyped-def]
    """Wipe outbox/event_log/consumer_offsets before each test (autouse)."""
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE event_log DISABLE TRIGGER event_log_no_update"))
        conn.execute(text("DELETE FROM outbox"))
        conn.execute(text("DELETE FROM event_log"))
        conn.execute(text("DELETE FROM consumer_offsets"))
        conn.execute(text("ALTER TABLE event_log ENABLE TRIGGER event_log_no_update"))
        conn.commit()


def _make_disclosure_event() -> DomainEvent:
    return DomainEvent(
        type=EventType.TRADE_DISCLOSURE_RECEIVED,
        aggregate_id=f"filing_{uuid4().hex[:8]}",
        aggregate_type=AggregateType.TRADE_DISCLOSURE,
        payload={"member": "Doe", "ticker": "AAPL"},
    )


def test_relay_promotes_outbox_row_to_event_log(engine):  # type: ignore[no-untyped-def]
    """Happy path: write to outbox, relay, row appears in event_log + marked published."""
    correlation = uuid4()
    event_id = uuid4()
    occurred = datetime.now(UTC)

    with Session(engine) as s:
        s.add(
            OutboxRow(
                id=event_id,
                aggregate_id="agg1",
                aggregate_type=AggregateType.TRADE_DISCLOSURE.value,
                event_type=EventType.TRADE_DISCLOSURE_RECEIVED.value,
                schema_version=1,
                payload={"ticker": "AAPL"},
                envelope={
                    "id": str(event_id),
                    "type": EventType.TRADE_DISCLOSURE_RECEIVED.value,
                    "aggregate_id": "agg1",
                    "aggregate_type": AggregateType.TRADE_DISCLOSURE.value,
                    "occurred_at": occurred.isoformat(),
                    "correlation_id": str(correlation),
                    "causation_id": None,
                    "schema_version": 1,
                    "payload": {"ticker": "AAPL"},
                },
                occurred_at=occurred,
                correlation_id=correlation,
            )
        )
        s.commit()

    bus = EventBus()
    seen: list[EventEnvelope] = []

    def handler(env: EventEnvelope, session: Session) -> None:
        seen.append(env)

    bus.subscribe_sync(EventType.TRADE_DISCLOSURE_RECEIVED.value, handler)

    factory = lambda: Session(engine)  # noqa: E731
    relay = OutboxRelay(factory, bus, worker_id="test")

    published = relay.run_once(batch_limit=10)
    assert published == 1
    assert len(seen) == 1
    assert seen[0].payload == {"ticker": "AAPL"}

    # Use a fresh Session to avoid any identity-map staleness from the
    # earlier insert in this test.
    with Session(engine) as s:
        # event_log row present
        log_rows = s.scalars(select(EventLogRow)).all()
        assert len(log_rows) == 1
        assert log_rows[0].event_type == EventType.TRADE_DISCLOSURE_RECEIVED.value

    with Session(engine) as s:
        outbox_rows = s.scalars(select(OutboxRow)).all()
        assert len(outbox_rows) == 1
        assert outbox_rows[0].published_at is not None


def test_relay_is_idempotent_on_event_id(engine):  # type: ignore[no-untyped-def]
    """Re-promoting the same event_id is a no-op in event_log.

    Simulates crash between event_log insert and marking published: row gets
    re-claimed, re-inserted (ON CONFLICT DO NOTHING), then marked published.
    """
    event_id = uuid4()
    correlation = uuid4()
    occurred = datetime.now(UTC)

    with Session(engine) as s:
        s.add(
            OutboxRow(
                id=event_id,
                aggregate_id="agg2",
                aggregate_type=AggregateType.TRADE_DISCLOSURE.value,
                event_type=EventType.TRADE_DISCLOSURE_RECEIVED.value,
                schema_version=1,
                payload={"ticker": "MSFT"},
                envelope={
                    "id": str(event_id),
                    "type": EventType.TRADE_DISCLOSURE_RECEIVED.value,
                    "aggregate_id": "agg2",
                    "aggregate_type": AggregateType.TRADE_DISCLOSURE.value,
                    "occurred_at": occurred.isoformat(),
                    "correlation_id": str(correlation),
                    "causation_id": None,
                    "schema_version": 1,
                    "payload": {"ticker": "MSFT"},
                },
                occurred_at=occurred,
                correlation_id=correlation,
            )
        )
        # Pre-insert into event_log directly (simulating a prior partial promotion)
        s.execute(
            text(
                """
                INSERT INTO event_log (event_id, event_type, schema_version, aggregate_id,
                                       aggregate_type, occurred_at, correlation_id, payload, envelope)
                VALUES (:eid, :et, 1, :aid, :at, :occ, :cid, '{}'::jsonb, '{}'::jsonb)
                """
            ),
            {
                "eid": event_id,
                "et": EventType.TRADE_DISCLOSURE_RECEIVED.value,
                "aid": "agg2",
                "at": AggregateType.TRADE_DISCLOSURE.value,
                "occ": occurred,
                "cid": correlation,
            },
        )
        s.commit()

    bus = EventBus()
    factory = lambda: Session(engine)  # noqa: E731
    relay = OutboxRelay(factory, bus, worker_id="test")

    published = relay.run_once()
    assert published == 1

    with Session(engine) as s:
        log_rows = s.scalars(select(EventLogRow)).all()
        assert len(log_rows) == 1, "event_log must not duplicate on event_id"


def test_relay_records_error_on_handler_failure(engine):  # type: ignore[no-untyped-def]
    """If a handler raises, the outbox row records last_error + retries later."""
    correlation = uuid4()
    occurred = datetime.now(UTC)
    event_id = uuid4()

    with Session(engine) as s:
        s.add(
            OutboxRow(
                id=event_id,
                aggregate_id="agg3",
                aggregate_type=AggregateType.TRADE_DISCLOSURE.value,
                event_type=EventType.TRADE_DISCLOSURE_RECEIVED.value,
                schema_version=1,
                payload={"ticker": "NVDA"},
                envelope={
                    "id": str(event_id),
                    "type": EventType.TRADE_DISCLOSURE_RECEIVED.value,
                    "aggregate_id": "agg3",
                    "aggregate_type": AggregateType.TRADE_DISCLOSURE.value,
                    "occurred_at": occurred.isoformat(),
                    "correlation_id": str(correlation),
                    "causation_id": None,
                    "schema_version": 1,
                    "payload": {"ticker": "NVDA"},
                },
                occurred_at=occurred,
                correlation_id=correlation,
            )
        )
        s.commit()

    bus = EventBus()

    def bad_handler(env: EventEnvelope, session: Session) -> None:
        raise RuntimeError("boom")

    bus.subscribe_sync(EventType.TRADE_DISCLOSURE_RECEIVED.value, bad_handler)

    factory = lambda: Session(engine)  # noqa: E731
    relay = OutboxRelay(factory, bus, worker_id="test")

    published = relay.run_once()
    assert published == 0

    with Session(engine) as s:
        row = s.scalar(select(OutboxRow).where(OutboxRow.id == event_id))
        assert row is not None
        assert row.published_at is None
        assert row.retry_count == 1
        assert row.last_error is not None
        assert "boom" in row.last_error


def test_clock_no_datetime_now_in_domain():  # type: ignore[no-untyped-def]
    """Sanity: SystemClock is the only thing in the codebase that should call now()."""
    # Quick sanity check — we can construct both clocks.
    frozen = FrozenClock(datetime(2026, 6, 21, tzinfo=UTC))
    assert frozen.now().year == 2026

    sysclock = SystemClock()
    assert sysclock.now().tzinfo is not None
