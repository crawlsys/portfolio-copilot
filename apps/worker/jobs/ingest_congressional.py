"""Scheduled job: ingest Congressional trade disclosures from Quiver.

Runs hourly during market hours, daily otherwise. Calls the
IngestCongressionalDisclosures use case which fetches from the Quiver
adapter, dedupes, stores, and emits events.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from apps.common.settings import get_settings
from trading.adapters.quiver.client import QuiverClient
from trading.application.common.clock import SystemClock
from trading.application.common.unit_of_work import UnitOfWork
from trading.application.congressional.ingest_disclosures import (
    IngestCommand,
    execute,
)

_log = logging.getLogger(__name__)

# How many disclosures to fetch per poll. Quiver's recent endpoint returns
# in reverse chronological order; 100 is a sane default for hourly polling.
POLL_LIMIT = 100


async def run_ingest(since: date | None = None) -> None:
    """Fetch + store recent disclosures. Called by the scheduler."""
    settings = get_settings()
    if not settings.quiver_api_key:
        _log.warning("QUIVER_API_KEY not set — skipping congressional ingest")
        return

    engine = create_async_engine(
        settings.database_url.replace("+psycopg", "+psycopg_async"),
        poolclass=__import__("sqlalchemy.pool", fromlist=["NullPool"]).NullPool,
    )
    try:
        feed = QuiverClient(api_key=settings.quiver_api_key)
        clock = SystemClock()

        async with AsyncSession(engine, expire_on_commit=False) as session:
            uow = UnitOfWork(
                session=session,
                clock=clock,
                correlation_id=uuid4(),
            )
            async with uow:
                result = await execute(
                    IngestCommand(
                        correlation_id=uow.correlation_id,
                        actor="scheduler",
                        since=since,
                        limit=POLL_LIMIT,
                    ),
                    feed=feed,
                    uow=uow,
                )

        _log.info(
            "congressional ingest: fetched=%d inserted=%d duplicates=%d",
            result.fetched,
            result.inserted,
            result.duplicates_skipped,
        )

        if result.inserted > 0:
            for d in result.new_disclosures:
                sym = d.symbol.ticker if d.symbol else d.asset_description
                _log.info(
                    "  NEW: %s %s %s %s-%s (filed %s, traded %s, lag=%dd)",
                    d.member_name,
                    d.transaction_type.name,
                    sym,
                    d.amount_range_low,
                    d.amount_range_high,
                    d.disclosure_date,
                    d.transaction_date,
                    d.lag_days,
                )
    finally:
        await engine.dispose()


def run_ingest_sync() -> None:
    """Sync wrapper for APScheduler (which doesn't drive an event loop by default)."""
    asyncio.run(run_ingest())
