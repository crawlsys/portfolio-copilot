"""OutboxRelay — promotes outbox rows to durable event_log + in-process bus.

Algorithm (at-least-once):
1. Claim unpublished rows with `FOR UPDATE SKIP LOCKED`.
2. For each: insert into event_log (ON CONFLICT DO NOTHING by event_id).
3. Publish to in-process bus — handlers run with the session open so they
   can write follow-up events into the SAME transaction.
4. Mark outbox row published_at.

If the process dies after step 2 or 3 before step 4, the row is retried on
the next pass. event_log ON CONFLICT (event_id) DO NOTHING prevents dupes
in the log; consumers dedupe via consumer_offsets.

This module is sync on the SA sync session for clarity. The worker process
calls `relay.run_once()` in a loop.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from trading.application.common.event_bus import EventBus
from trading.application.common.event_envelope import EventEnvelope

if TYPE_CHECKING:
    from collections.abc import Callable

    SessionFactory = Callable[[], Session]

_log = logging.getLogger(__name__)

CLAIM_SQL = text(
    """
    WITH claimed AS (
        SELECT id
        FROM outbox
        WHERE published_at IS NULL
          AND (locked_at IS NULL OR locked_at < now() - interval '5 minutes')
        ORDER BY occurred_at, id
        LIMIT :limit
        FOR UPDATE SKIP LOCKED
    )
    UPDATE outbox o
    SET locked_at = now(), locked_by = :worker_id
    FROM claimed
    WHERE o.id = claimed.id
    RETURNING o.id, o.envelope
    """
)

INSERT_EVENT_LOG_SQL = text(
    """
    INSERT INTO event_log (
        event_id, event_type, schema_version, aggregate_id, aggregate_type,
        occurred_at, correlation_id, causation_id, payload, envelope
    )
    VALUES (
        :event_id, :event_type, :schema_version, :aggregate_id, :aggregate_type,
        :occurred_at, :correlation_id, :causation_id,
        CAST(:payload AS jsonb), CAST(:envelope AS jsonb)
    )
    ON CONFLICT (event_id) DO NOTHING
    """
)

MARK_PUBLISHED_SQL = text(
    "UPDATE outbox SET published_at = now(), locked_at = NULL, locked_by = NULL WHERE id = :id"
)

RECORD_ERROR_SQL = text(
    """
    UPDATE outbox
    SET retry_count = retry_count + 1,
        locked_at = NULL, locked_by = NULL,
        last_error = :error
    WHERE id = :id
    """
)


class OutboxRelay:
    """Promotes unpublished outbox rows to durable event_log + bus."""

    def __init__(
        self,
        session_factory: SessionFactory,
        bus: EventBus,
        worker_id: str | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.bus = bus
        self.worker_id = worker_id or f"relay-{uuid4().hex[:8]}"

    def run_once(self, batch_limit: int = 100) -> int:
        """Process one batch. Returns the number of rows published."""
        published = 0
        with self.session_factory() as session:
            rows = session.execute(
                CLAIM_SQL, {"limit": batch_limit, "worker_id": self.worker_id}
            ).all()
            session.commit()  # release the claim locks but keep the locked_at marker

            for row in rows:
                row_id, envelope_dict = row[0], row[1]
                try:
                    envelope = EventEnvelope.from_dict(envelope_dict)
                    self._promote(session, envelope)
                    # Publish to bus inside the same tx as the event_log insert,
                    # so follow-up events written by handlers land in outbox
                    # atomically with the promotion.
                    session.commit()
                    published += 1
                except Exception as exc:  # noqa: BLE001
                    _log.exception("Failed to promote outbox row %s", row_id)
                    session.rollback()
                    self._record_error(row_id, repr(exc)[:2000])

        return published

    def _promote(self, session: Session, env: EventEnvelope) -> None:
        # 1. Append to durable event_log (idempotent on event_id).
        session.execute(
            INSERT_EVENT_LOG_SQL,
            {
                "event_id": env.id,
                "event_type": env.type.value,
                "schema_version": env.schema_version,
                "aggregate_id": env.aggregate_id,
                "aggregate_type": env.aggregate_type.value,
                "occurred_at": env.occurred_at,
                "correlation_id": env.correlation_id,
                "causation_id": env.causation_id,
                "payload": _to_jsonb(env.payload),
                "envelope": _to_jsonb(env.to_dict()),
            },
        )

        # 2. Deliver to in-process sync handlers. They may write follow-up
        #    events into the SAME session's outbox — claimed on the next
        #    run_once() pass. Async handlers run separately (driven by the
        #    worker's event loop, reading from event_log).
        self.bus.publish_sync(env, session)

        # 3. Mark published.
        session.execute(MARK_PUBLISHED_SQL, {"id": env.id})

    def _record_error(self, row_id: object, error: str) -> None:
        with self.session_factory() as session:
            session.execute(RECORD_ERROR_SQL, {"id": row_id, "error": error})
            session.commit()


def _to_jsonb(value: object) -> str:
    """Render to JSON string for CAST(:x AS jsonb)."""
    return json.dumps(value, default=_json_default, separators=(",", ":"))


def _json_default(obj: object) -> object:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Cannot serialize {type(obj).__name__}")
