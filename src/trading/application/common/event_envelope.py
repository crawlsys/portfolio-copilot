"""Event envelope (de)serialization + ID generation helpers.

Application code raises `DomainEvent`s; the UnitOfWork wraps them in
`EventEnvelope`s before writing to the outbox. The relay writes envelopes
verbatim into the durable event_log table (JSONB column).

Envelope IDs are generated here (uuid4) — never reused across events, which
is what consumers dedupe on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from trading.domain import AggregateType, CorrelationId, DomainEvent, EventType


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """A persisted domain event. Immutable; what the durable log stores."""

    id: UUID
    type: EventType
    aggregate_id: str
    aggregate_type: AggregateType
    occurred_at: datetime
    correlation_id: UUID
    payload: dict[str, Any]
    schema_version: int = 1
    causation_id: UUID | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe dict for JSONB storage."""
        return {
            "id": str(self.id),
            "type": self.type.value,
            "aggregate_id": self.aggregate_id,
            "aggregate_type": self.aggregate_type.value,
            "occurred_at": self.occurred_at.isoformat(),
            "correlation_id": str(self.correlation_id),
            "causation_id": str(self.causation_id) if self.causation_id else None,
            "schema_version": self.schema_version,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventEnvelope:
        return cls(
            id=UUID(data["id"]),
            type=EventType(data["type"]),
            aggregate_id=data["aggregate_id"],
            aggregate_type=AggregateType(data["aggregate_type"]),
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            correlation_id=UUID(data["correlation_id"]),
            payload=data["payload"],
            schema_version=data.get("schema_version", 1),
            causation_id=UUID(data["causation_id"]) if data.get("causation_id") else None,
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str, separators=(",", ":"))


def make_envelope(
    event: DomainEvent,
    correlation_id: UUID | CorrelationId,
    occurred_at: datetime,
    causation_id: UUID | None = None,
) -> EventEnvelope:
    """Wrap a DomainEvent in an EventEnvelope, minting a fresh event id."""
    return EventEnvelope(
        id=uuid4(),
        type=event.type,
        aggregate_id=event.aggregate_id,
        aggregate_type=event.aggregate_type,
        occurred_at=occurred_at,
        correlation_id=UUID(str(correlation_id)),
        payload=event.payload,
        schema_version=event.schema_version,
        causation_id=causation_id,
    )
