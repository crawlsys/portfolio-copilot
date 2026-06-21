"""UnitOfWork — transactional boundary for the outbox pattern.

Domain logic collects DomainEvents via `uow.collect(...)`. On commit, those
events are written to the `outbox` table in the same database transaction
as the state changes. Events are durable iff the transaction commits.

Usage in a use case:
    async with uow:
        await uow.session.execute(...)
        uow.collect(DomainEvent(...))
    # implicit commit on context exit; events in outbox; relay promotes next

The UnitOfWork does NOT publish to the in-process bus. The OutboxRelay does
that, after the transaction commits, so handlers run with durable state.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING
from uuid import UUID

from trading.adapters.persistence.models import OutboxRow
from trading.application.common.event_envelope import EventEnvelope, make_envelope
from trading.domain import DomainEvent

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from trading.application.common.clock import ClockPort


class UnitOfWork:
    """Async transactional UoW. Enrolls events into outbox on commit.

    Note: `collect()` is sync; events are buffered in memory. `__aexit__`
    writes them to the outbox table within the SA session's transaction.
    """

    def __init__(
        self,
        session: AsyncSession,
        clock: ClockPort,
        correlation_id: UUID,
    ) -> None:
        self.session = session
        self.clock = clock
        self.correlation_id = correlation_id
        self._events: list[DomainEvent] = []
        self._causation_id: UUID | None = None

    def collect(self, *events: DomainEvent) -> None:
        self._events.extend(events)

    def set_causation(self, causation_id: UUID | None) -> None:
        """Set the causation_id for the next flush — used when this UoW is
        reacting to a prior event (handler chain)."""
        self._causation_id = causation_id

    async def __aenter__(self) -> UnitOfWork:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is not None:
            await self.session.rollback()
            return
        await self.commit()

    async def commit(self) -> None:
        """Flush collected events to outbox in the session's transaction, then commit."""
        now: datetime = self.clock.now()
        envelopes = [
            make_envelope(
                event=e,
                correlation_id=self.correlation_id,
                occurred_at=now,
                causation_id=self._causation_id,
            )
            for e in self._events
        ]
        for env in envelopes:
            await self._insert_outbox_row(env)
        await self.session.commit()
        self._events.clear()
        self._causation_id = None

    async def _insert_outbox_row(self, env: EventEnvelope) -> None:
        self.session.add(
            OutboxRow(
                id=env.id,
                aggregate_id=env.aggregate_id,
                aggregate_type=env.aggregate_type.value,
                event_type=env.type.value,
                schema_version=env.schema_version,
                payload=env.payload,
                envelope=env.to_dict(),
                occurred_at=env.occurred_at,
                correlation_id=env.correlation_id,
                causation_id=env.causation_id,
            )
        )
        # Don't flush — let the commit above flush everything together.
        # SA will assign IDs and write in one transaction.

    async def __aiter__(self) -> AsyncIterator[EventEnvelope]:  # pragma: no cover
        """Yield envelopes as they were committed. Useful for tests."""
        now = self.clock.now()
        for e in self._events:
            yield make_envelope(
                event=e,
                correlation_id=self.correlation_id,
                occurred_at=now,
                causation_id=self._causation_id,
            )
