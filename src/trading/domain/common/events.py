"""Domain event envelope — what aggregates raise before persistence wraps it.

The persistence layer (UnitOfWork) wraps these in a full `EventEnvelope`
with id, occurred_at, correlation_id, causation_id before writing to the
outbox. Domain code raises `DomainEvent`s; it doesn't know about the envelope.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from trading.domain.common.event_types import AggregateType, EventType


class EventPayload(Protocol):
    """Structural protocol for typed event payloads.

    Concrete payloads (in each context's `events.py`) are frozen dataclasses
    that satisfy this shape. The protocol is structural — no inheritance.
    """

    def to_dict(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """An event raised by an aggregate, awaiting persistence.

    `payload` is an opaque dict here (typed per event in each context's
    events module) — keeps the domain core decoupled from Pydantic.
    """

    type: EventType
    aggregate_id: str
    aggregate_type: AggregateType
    payload: dict[str, Any]
    schema_version: int = 1
