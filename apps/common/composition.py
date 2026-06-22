"""Composition root — wires adapters to use cases.

This is the ONLY place that knows concrete adapter classes. Everything
upstream (api/mcp/worker) depends on the resulting objects, never on
adapter classes directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from trading.adapters.fake.broker import make_default_fake_broker
from trading.adapters.notifications import (
    LoggingNotifier,
    NotifierPort,
    NtfyNotifier,
    PushoverNotifier,
)
from trading.adapters.object_store.garage import GarageBlobStore
from trading.adapters.object_store.protocol import BlobStore
from trading.adapters.ports.broker import BrokerPort
from trading.application.common.clock import ClockPort, SystemClock
from trading.application.common.event_bus import EventBus
from trading.application.market_data.refresh_quotes import (
    MarketDataPort,
    NoMarketData,
)


@dataclass
class Composition:
    """Wired application — broker, clock, bus, engine, market data, notifier."""

    broker: BrokerPort
    clock: ClockPort
    bus: EventBus
    engine: AsyncEngine | None
    blob_store: BlobStore | None
    market_data: MarketDataPort
    notifier: NotifierPort


def make_composition(
    *,
    broker_mode: str = "fake",
    database_url: str = "",
    massive_api_key: str = "",
    push_provider: str = "",
    pushover_api_token: str = "",
    pushover_user_key: str = "",
    ntfy_server_url: str = "https://ntfy.sh",
    ntfy_topic: str = "",
    ntfy_auth_token: str = "",
    s3_endpoint_url: str = "",
    s3_bucket: str = "tracker-blobs",
    aws_access_key_id: str = "",
    aws_secret_access_key: str = "",
) -> Composition:
    """Construct the wired application based on settings."""
    bus = EventBus()
    clock = SystemClock()

    # Broker
    broker: BrokerPort = make_default_fake_broker()

    # Market data
    if massive_api_key:
        from trading.adapters.massive.client import MassiveClient  # noqa: PLC0415

        market_data: MarketDataPort = cast(MarketDataPort, MassiveClient(api_key=massive_api_key))
    else:
        market_data = NoMarketData()

    # Notifier — Pushover (preferred), ntfy, or LoggingNotifier fallback
    if push_provider == "pushover" and pushover_api_token and pushover_user_key:
        notifier: NotifierPort = PushoverNotifier(
            api_token=pushover_api_token,
            user_key=pushover_user_key,
        )
    elif push_provider == "ntfy" and ntfy_topic:
        notifier = NtfyNotifier(
            server_url=ntfy_server_url,
            topic=ntfy_topic,
            auth_token=ntfy_auth_token or None,
        )
    else:
        notifier = LoggingNotifier()

    # Blob store (Garage/S3)
    blob_store: BlobStore | None = None
    if s3_endpoint_url:
        blob_store = GarageBlobStore(
            endpoint_url=s3_endpoint_url,
            bucket=s3_bucket,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
        )

    # DB engine
    engine: AsyncEngine | None = None
    if database_url:
        engine = create_async_engine(_to_async_url(database_url))

    return Composition(
        broker=broker,
        clock=clock,
        bus=bus,
        engine=engine,
        blob_store=blob_store,
        market_data=market_data,
        notifier=notifier,
    )


def session_factory(comp: Composition) -> AsyncSession:
    """Build a fresh AsyncSession bound to the composition's engine."""
    if comp.engine is None:
        raise RuntimeError("No engine configured — set DATABASE_URL")
    return AsyncSession(comp.engine, expire_on_commit=False)


def _to_async_url(database_url: str) -> str:
    """Convert a sync DATABASE_URL to its async equivalent."""
    return database_url.replace("+psycopg", "+psycopg_async")


__all__ = ["Composition", "make_composition", "session_factory"]
