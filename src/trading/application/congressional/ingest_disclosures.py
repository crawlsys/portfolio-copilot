"""IngestCongressionalDisclosures use case.

Fetches recent trade disclosures from the CongressionalFeedPort (Quiver),
deduplicates against what's already stored, inserts new ones, and emits
TradeDisclosureReceived events for each new disclosure.

Called by the worker's scheduled job (hourly during market hours, daily
otherwise). Also exposes a backfill method for historical data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from trading.adapters.persistence.models import TradeDisclosureRow
from trading.domain import (
    AggregateType,
    DomainEvent,
    EventType,
    TradeDisclosure,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from trading.adapters.quiver.client import QuiverClient
    from trading.application.common.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class IngestCommand:
    correlation_id: UUID
    actor: str  # "scheduler" | "api" | "agent"
    since: date | None = None  # None = fetch latest
    limit: int = 100


@dataclass(frozen=True, slots=True)
class IngestResult:
    fetched: int
    inserted: int
    duplicates_skipped: int
    ingested_at: datetime
    new_disclosures: tuple[TradeDisclosure, ...]


async def execute(
    cmd: IngestCommand,
    feed: QuiverClient,
    uow: UnitOfWork,
) -> IngestResult:
    """Fetch from Quiver, dedupe, store, emit events."""
    now = uow.clock.now()
    session = uow.session

    # 1. Fetch from the feed
    raw_disclosures = await feed.get_recent_disclosures(since=cmd.since, limit=cmd.limit)

    # 2. Find which filing_ids are already stored (dedupe)
    filing_ids = tuple(d.filing_id for d in raw_disclosures)
    existing_ids = await _find_existing_filing_ids(session, filing_ids)
    existing_set = set(existing_ids)

    # 3. Insert new ones + collect events
    new_disclosures: list[TradeDisclosure] = []
    events: list[DomainEvent] = []

    for disclosure in raw_disclosures:
        if disclosure.filing_id in existing_set:
            continue

        await _insert_disclosure(session, disclosure, now)
        new_disclosures.append(disclosure)
        events.append(_make_disclosure_event(disclosure, now))

    if events:
        uow.collect(*events)

    return IngestResult(
        fetched=len(raw_disclosures),
        inserted=len(new_disclosures),
        duplicates_skipped=len(raw_disclosures) - len(new_disclosures),
        ingested_at=now,
        new_disclosures=tuple(new_disclosures),
    )


async def backfill(
    feed: QuiverClient,
    uow: UnitOfWork,
    start: date,
    end: date,
) -> IngestResult:
    """Backfill historical disclosures. Paginates through the feed."""
    now = uow.clock.now()
    session = uow.session

    total_fetched = 0
    total_inserted = 0
    total_skipped = 0
    all_new: list[TradeDisclosure] = []

    async for batch in feed.backfill(start, end):
        filing_ids = tuple(d.filing_id for d in batch)
        existing_ids = await _find_existing_filing_ids(session, filing_ids)
        existing_set = set(existing_ids)
        events: list[DomainEvent] = []

        for disclosure in batch:
            if disclosure.filing_id in existing_set:
                total_skipped += 1
                continue
            await _insert_disclosure(session, disclosure, now)
            all_new.append(disclosure)
            total_inserted += 1
            events.append(_make_disclosure_event(disclosure, now))

        total_fetched += len(batch)
        if events:
            uow.collect(*events)

    return IngestResult(
        fetched=total_fetched,
        inserted=total_inserted,
        duplicates_skipped=total_skipped,
        ingested_at=now,
        new_disclosures=tuple(all_new),
    )


# --- Helpers -----------------------------------------------------------------


async def _find_existing_filing_ids(
    session: AsyncSession, filing_ids: tuple[str, ...]
) -> tuple[str, ...]:
    """Return the subset of filing_ids already in the DB."""
    if not filing_ids:
        return ()
    result = await session.execute(
        select(TradeDisclosureRow.filing_id).where(TradeDisclosureRow.filing_id.in_(filing_ids))
    )
    return tuple(result.scalars().all())


async def _insert_disclosure(
    session: AsyncSession, disclosure: TradeDisclosure, now: datetime
) -> None:
    """Insert a disclosure row. ON CONFLICT DO NOTHING — dedupes by filing_id.

    Handles both cross-batch dups (already in DB) AND intra-batch dups
    (Quiver returns the same filing_id twice across pages).
    """
    stmt = pg_insert(TradeDisclosureRow).values(
        filing_id=disclosure.filing_id,
        member_id=disclosure.member_id,
        member_name=disclosure.member_name,
        symbol=disclosure.symbol.ticker if disclosure.symbol else None,
        asset_class="EQUITY",
        asset_description=disclosure.asset_description,
        transaction_type=disclosure.transaction_type.name,
        transaction_date=disclosure.transaction_date,
        disclosure_date=disclosure.disclosure_date,
        amount_range_low=disclosure.amount_range_low,
        amount_range_high=disclosure.amount_range_high,
        raw_blob_key=disclosure.raw_blob_key,
        ingested_at=now,
    )
    stmt = stmt.on_conflict_do_nothing(index_elements=["filing_id"])
    await session.execute(stmt)


def _make_disclosure_event(disclosure: TradeDisclosure, now: datetime) -> DomainEvent:
    return DomainEvent(
        type=EventType.TRADE_DISCLOSURE_RECEIVED,
        aggregate_id=disclosure.filing_id,
        aggregate_type=AggregateType.TRADE_DISCLOSURE,
        payload={
            "filing_id": disclosure.filing_id,
            "member_id": disclosure.member_id,
            "member_name": disclosure.member_name,
            "symbol": disclosure.symbol.ticker if disclosure.symbol else None,
            "transaction_type": disclosure.transaction_type.name,
            "transaction_date": disclosure.transaction_date.isoformat(),
            "disclosure_date": disclosure.disclosure_date.isoformat(),
            "amount_range_low": disclosure.amount_range_low,
            "amount_range_high": disclosure.amount_range_high,
            "lag_days": disclosure.lag_days,
            "received_at": now.isoformat(),
        },
    )


__all__ = ["IngestCommand", "IngestResult", "execute", "backfill"]
