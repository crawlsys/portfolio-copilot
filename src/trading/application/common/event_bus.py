"""In-process typed event bus.

Per red-team recommendation: a custom `dict[EventType, list[Handler]]` over
blinker/dramatiq. The durable log + outbox already handle persistence; the
bus just delivers events to in-process handlers.

Two flavors of handler, to support both async use cases (FastAPI path) and
sync ones (the relay worker, which uses a sync SA session):

- `subscribe(event_type, async_handler)` — async; called via `await bus.publish(...)`
- `subscribe_sync(event_type, sync_handler)` — sync; called via `bus.publish_sync(...)`

Handlers receive `(envelope, session)` so they can read fresh state for
projections and enroll follow-up events into the SAME transaction.

Delivery is at-least-once. Handlers MUST be idempotent (use consumer_offsets).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from trading.application.common.event_envelope import EventEnvelope

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Session as SyncSession

AsyncHandler = Callable[[EventEnvelope, "AsyncSession"], Awaitable[None]]
SyncHandler = Callable[[EventEnvelope, "SyncSession"], None]


class EventBus:
    """Typed pub/sub for domain events. Sync + async handlers supported."""

    def __init__(self) -> None:
        self._async_handlers: dict[str, list[AsyncHandler]] = defaultdict(list)
        self._sync_handlers: dict[str, list[SyncHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: AsyncHandler) -> None:
        """Register an async handler for an event type (EventType.value or str)."""
        key = event_type.value if hasattr(event_type, "value") else event_type
        self._async_handlers[key].append(handler)

    def subscribe_sync(self, event_type: str, handler: SyncHandler) -> None:
        """Register a sync handler. Used by the relay worker."""
        key = event_type.value if hasattr(event_type, "value") else event_type
        self._sync_handlers[key].append(handler)

    async def publish(self, envelope: EventEnvelope, session: AsyncSession) -> None:
        """Deliver to all subscribed async handlers, sequentially.

        A raised exception stops delivery and bubbles to the caller (relay),
        which retries the whole envelope.
        """
        for handler in self._async_handlers.get(envelope.type.value, []):
            await handler(envelope, session)

    def publish_sync(self, envelope: EventEnvelope, session: SyncSession) -> None:
        """Deliver to all subscribed sync handlers. Used by the relay worker."""
        for handler in self._sync_handlers.get(envelope.type.value, []):
            handler(envelope, session)

    def handler_count(self, event_type: str) -> int:
        """Test helper: total handlers (async + sync) subscribed."""
        return len(self._async_handlers.get(event_type, [])) + len(
            self._sync_handlers.get(event_type, [])
        )
