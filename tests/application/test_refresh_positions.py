"""Tests for RefreshPositions use case.

End-to-end: FakeBroker → use case → Postgres upsert → outbox events.
Verifies:
- New positions get inserted locally; PositionReconciled emitted
- Existing positions with material drift emit PositionDriftDetected
- Quantities below epsilon don't emit drift
- Positions the broker no longer reports get deleted locally + flagged
- All events land in outbox (transactional with state writes)
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from trading.adapters.fake.broker import FakeBroker
from trading.adapters.persistence.models import BrokerAccountRow, OutboxRow, PositionRow
from trading.application.common.clock import FrozenClock
from trading.application.common.unit_of_work import UnitOfWork
from trading.application.portfolio.refresh_positions import (
    PNL_DRIFT_THRESHOLD,
    RefreshPositionsCommand,
    execute,
)
from trading.domain import EventType, Money, Symbol

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL required for refresh_positions tests",
)


def _async_url() -> str:
    """DATABASE_URL uses +psycopg; async needs +psycopg_async."""
    return os.environ["DATABASE_URL"].replace("+psycopg", "+psycopg_async")


@pytest.fixture()
def fake_broker() -> FakeBroker:
    broker = FakeBroker()
    broker.add_account(
        account_id="acct-1",
        nickname="Test",
        masked_schwab_id="****0001",
        cash=Money.usd("100000"),
    )
    return broker


@pytest.fixture(autouse=True)
def _clean(engine):  # type: ignore[no-untyped-def]
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM outbox"))
        conn.execute(text("DELETE FROM positions"))
        conn.execute(text("DELETE FROM broker_accounts"))
        conn.execute(
            text("ALTER TABLE event_log DISABLE TRIGGER event_log_no_update")
        )
        conn.execute(text("DELETE FROM event_log"))
        conn.execute(text("ALTER TABLE event_log ENABLE TRIGGER event_log_no_update"))
        conn.commit()


@pytest.fixture()
def engine():

    eng = create_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    yield eng
    eng.dispose()


@pytest.fixture()
async def async_engine():
    eng = create_async_engine(_async_url(), poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest.fixture()
async def async_session(async_engine):  # type: ignore[no-untyped-def]
    async with AsyncSession(async_engine, expire_on_commit=False) as session:
        # Seed the broker_accounts row that positions FK to.
        session.add(
            BrokerAccountRow(
                account_id="acct-1",
                nickname="Test",
                masked_schwab_id="****0001",
                account_type="TAXABLE",
                margin_enabled=False,
                allowed_instruments=["EQUITY"],
                is_paper=True,
            )
        )
        await session.commit()
        yield session


@pytest.fixture()
def frozen_now() -> datetime:
    return datetime(2026, 6, 21, 14, 30, tzinfo=UTC)


@pytest.fixture()
async def uow(async_session, frozen_now):  # type: ignore[no-untyped-def]
    clock = FrozenClock(frozen_now)
    return UnitOfWork(
        session=async_session,
        clock=clock,
        correlation_id=uuid4(),
    )


# --- Tests -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_refresh_inserts_all_positions_and_emits_reconciled(
    fake_broker: FakeBroker, uow: UnitOfWork, async_session
) -> None:
    """Account has no prior local state; all broker positions are new."""
    fake_broker.set_position(
        account_id="acct-1",
        symbol=Symbol("AAPL"),
        quantity=Decimal("100"),
        average_cost=Money.usd("150"),
        market_value=Money.usd("17500"),
    )
    fake_broker.set_position(
        account_id="acct-1",
        symbol=Symbol("MSFT"),
        quantity=Decimal("50"),
        average_cost=Money.usd("300"),
        market_value=Money.usd("20000"),
    )

    async with uow:
        result = await execute(
            RefreshPositionsCommand(
                account_id="acct-1",
                correlation_id=uuid4(),
                actor="test",
            ),
            broker=fake_broker,
            uow=uow,
        )

    assert result.refreshed_positions.__len__() == 2
    # First refresh = every position is "new" = drift detected.
    assert result.drift_detected is True

    # Outbox has 2 reconciled + 2 drift events = 4 total.
    rows = await async_session.execute(select(OutboxRow))
    outbox = rows.scalars().all()
    types = {r.event_type for r in outbox}
    assert EventType.POSITION_RECONCILED.value in types
    assert EventType.POSITION_DRIFT_DETECTED.value in types


@pytest.mark.asyncio
async def test_no_drift_when_position_unchanged(
    fake_broker: FakeBroker, uow: UnitOfWork, async_session
) -> None:
    """Second refresh with identical state emits only reconciled, no drift."""
    # Seed initial state directly in DB to simulate prior refresh.
    async_session.add(
        PositionRow(
            account_id="acct-1",
            symbol="AAPL",
            asset_class="EQUITY",
            quantity=Decimal("100"),
            average_cost=Decimal("150"),
            average_cost_currency="USD",
            market_value=Decimal("17500"),
            unrealized_pnl=Decimal("2500"),
            as_of=datetime(2026, 6, 20, tzinfo=UTC),
        )
    )
    await async_session.commit()

    fake_broker.set_position(
        account_id="acct-1",
        symbol=Symbol("AAPL"),
        quantity=Decimal("100"),
        average_cost=Money.usd("150"),
        market_value=Money.usd("17500"),
    )

    async with uow:
        result = await execute(
            RefreshPositionsCommand(
                account_id="acct-1", correlation_id=uuid4(), actor="test"
            ),
            broker=fake_broker,
            uow=uow,
        )

    assert result.drift_detected is False

    rows = await async_session.execute(select(OutboxRow))
    types = {r.event_type for r in rows.scalars().all()}
    assert EventType.POSITION_RECONCILED.value in types
    assert EventType.POSITION_DRIFT_DETECTED.value not in types


@pytest.mark.asyncio
async def test_quantity_drift_emits_drift_event(
    fake_broker: FakeBroker, uow: UnitOfWork, async_session
) -> None:
    """Quantity change above epsilon → drift event."""
    async_session.add(
        PositionRow(
            account_id="acct-1",
            symbol="AAPL",
            asset_class="EQUITY",
            quantity=Decimal("100"),
            average_cost=Decimal("150"),
            average_cost_currency="USD",
            market_value=Decimal("17500"),
            unrealized_pnl=Decimal("2500"),
            as_of=datetime(2026, 6, 20, tzinfo=UTC),
        )
    )
    await async_session.commit()

    fake_broker.set_position(
        account_id="acct-1",
        symbol=Symbol("AAPL"),
        quantity=Decimal("110"),  # +10 shares = drift
        average_cost=Money.usd("150"),
        market_value=Money.usd("19250"),
    )

    async with uow:
        result = await execute(
            RefreshPositionsCommand(
                account_id="acct-1", correlation_id=uuid4(), actor="test"
            ),
            broker=fake_broker,
            uow=uow,
        )

    assert result.drift_detected is True
    assert any("qty" in d for d in result.drift_details)


@pytest.mark.asyncio
async def test_below_epsilon_quantity_change_no_drift(
    fake_broker: FakeBroker, uow: UnitOfWork, async_session
) -> None:
    """Sub-epsilon changes don't trigger drift (avoids noise on float dust)."""
    async_session.add(
        PositionRow(
            account_id="acct-1",
            symbol="AAPL",
            asset_class="EQUITY",
            quantity=Decimal("100"),
            average_cost=Decimal("150"),
            average_cost_currency="USD",
            market_value=Decimal("17500"),
            unrealized_pnl=Decimal("2500"),
            as_of=datetime(2026, 6, 20, tzinfo=UTC),
        )
    )
    await async_session.commit()

    # A tiny quantity bump (1e-5) below the epsilon (1e-4). P/L recomputed
    # by FakeBroker stays within Money's 4-dp limit.
    fake_broker.set_position(
        account_id="acct-1",
        symbol=Symbol("AAPL"),
        quantity=Decimal("100.00005"),  # 5e-5 < epsilon 1e-4
        average_cost=Money.usd("150"),
        market_value=Money.usd("17500.01"),  # sub-threshold P/L change too
    )

    async with uow:
        result = await execute(
            RefreshPositionsCommand(
                account_id="acct-1", correlation_id=uuid4(), actor="test"
            ),
            broker=fake_broker,
            uow=uow,
        )

    assert result.drift_detected is False


@pytest.mark.asyncio
async def test_orphan_position_local_only_is_deleted_and_flagged(
    fake_broker: FakeBroker, uow: UnitOfWork, async_session
) -> None:
    """Local has a position the broker no longer reports → delete + drift."""
    async_session.add(
        PositionRow(
            account_id="acct-1",
            symbol="ORPHAN",
            asset_class="EQUITY",
            quantity=Decimal("50"),
            average_cost=Decimal("100"),
            average_cost_currency="USD",
            market_value=Decimal("5000"),
            unrealized_pnl=Decimal("0"),
            as_of=datetime(2026, 6, 20, tzinfo=UTC),
        )
    )
    await async_session.commit()

    # Broker reports a different position; ORPHAN is gone.
    fake_broker.set_position(
        account_id="acct-1",
        symbol=Symbol("AAPL"),
        quantity=Decimal("10"),
        average_cost=Money.usd("100"),
        market_value=Money.usd("1000"),
    )

    async with uow:
        result = await execute(
            RefreshPositionsCommand(
                account_id="acct-1", correlation_id=uuid4(), actor="test"
            ),
            broker=fake_broker,
            uow=uow,
        )

    assert result.drift_detected is True
    assert any("ORPHAN" in d and "no longer reports" in d for d in result.drift_details)

    # ORPHAN row deleted from local positions.
    rows = await async_session.execute(
        select(PositionRow).where(PositionRow.symbol == "ORPHAN")
    )
    assert rows.scalars().first() is None


@pytest.mark.asyncio
async def test_pnl_drift_threshold_triggers_drift(
    fake_broker: FakeBroker, uow: UnitOfWork, async_session
) -> None:
    """P/L swing above $1 → drift (cost-basis kind)."""
    async_session.add(
        PositionRow(
            account_id="acct-1",
            symbol="AAPL",
            asset_class="EQUITY",
            quantity=Decimal("100"),
            average_cost=Decimal("150"),
            average_cost_currency="USD",
            market_value=Decimal("17500"),
            unrealized_pnl=Decimal("2500"),
            as_of=datetime(2026, 6, 20, tzinfo=UTC),
        )
    )
    await async_session.commit()

    # Same quantity, but P/L moved materially.
    fake_broker.set_position(
        account_id="acct-1",
        symbol=Symbol("AAPL"),
        quantity=Decimal("100"),
        average_cost=Money.usd("150"),
        market_value=Money.usd("18000"),  # +$500 → unrealized_pnl swings
    )

    async with uow:
        result = await execute(
            RefreshPositionsCommand(
                account_id="acct-1", correlation_id=uuid4(), actor="test"
            ),
            broker=fake_broker,
            uow=uow,
        )

    assert result.drift_detected is True
    assert any("pnl" in d for d in result.drift_details)
    # Sanity: threshold is reasonable.
    assert Decimal("1.00") == PNL_DRIFT_THRESHOLD
