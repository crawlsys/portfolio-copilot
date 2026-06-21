"""Composition root — wires adapters to use cases.

This is the ONLY place that knows concrete adapter classes. Everything
upstream (api/mcp/worker) depends on the resulting objects, never on
adapter classes directly.

`Composition` is constructed once at app startup. Tests construct their
own with FakeBroker + NullClock.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from trading.adapters.fake.broker import make_default_fake_broker
from trading.adapters.ports.broker import BrokerPort
from trading.application.common.clock import ClockPort, SystemClock
from trading.application.common.event_bus import EventBus


@dataclass
class Composition:
    """Wired application — broker, clock, bus, engine."""

    broker: BrokerPort
    clock: ClockPort
    bus: EventBus
    engine: AsyncEngine | None  # None when DB isn't configured (unit tests)


def make_composition(
    *,
    broker_mode: str = "fake",
    database_url: str = "",
) -> Composition:
    """Construct the wired application based on settings.

    broker_mode=fake is the v1 default. When broker_mode=schwab is set,
    SchwabBrokerAdapter is constructed (chunk: future, after Schwab app
    approval). For now, both paths route through make_default_fake_broker.
    """
    bus = EventBus()
    clock = SystemClock()

    if broker_mode == "schwab":
        # SchwabBrokerAdapter not yet implemented; fall back to FakeBroker
        # with a logged warning. Will be wired in chunk 9+.
        broker: BrokerPort = make_default_fake_broker()
    else:
        broker = make_default_fake_broker()

    engine: AsyncEngine | None = None
    if database_url:
        engine = create_async_engine(_to_async_url(database_url))

    return Composition(broker=broker, clock=clock, bus=bus, engine=engine)


def session_factory(comp: Composition):  # type: ignore[no-untyped-def]
    """Build a fresh AsyncSession bound to the composition's engine."""
    if comp.engine is None:
        raise RuntimeError("No engine configured — set DATABASE_URL")
    return AsyncSession(comp.engine, expire_on_commit=False)


def _to_async_url(database_url: str) -> str:
    """Convert a sync DATABASE_URL to its async equivalent."""
    return database_url.replace("+psycopg", "+psycopg_async")


__all__ = ["Composition", "make_composition", "session_factory"]
