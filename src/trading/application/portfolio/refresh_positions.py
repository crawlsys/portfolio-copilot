"""RefreshPositions use case.

Reads positions from the broker, upserts local cache, detects drift vs the
prior local snapshot, and emits PositionReconciled (+ PositionDriftDetected
if material) through the outbox.

This is the first end-to-end use case: it touches BrokerPort (read),
persistence (upsert), domain (drift detection), and UoW (event emission).
The MCP server and the FastAPI portfolio route both invoke it.

Why drift detection lives here (not in a separate job): per spec §Market
Regime, OrderFilled is authoritative for position changes *when execution
lands*. In v1 there is no execution, so reconciliation against the broker
is the only source of truth. Drift = anything that changed since last
refresh. The阈值 is a constant for now; tune via config later.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import delete

from trading.adapters.persistence.models import PositionRow
from trading.domain import (
    AggregateType,
    DomainEvent,
    DriftKind,
    EventType,
    Money,
    Position,
    Severity,
    Symbol,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from trading.adapters.ports.broker import BrokerPort
    from trading.application.common.unit_of_work import UnitOfWork


# Drift threshold: quantity difference > 0.0001 shares OR P/L swing > $1.
# Below this, we record a reconciled event but no drift event. Tunable.
QUANTITY_DRIFT_EPSILON = Decimal("0.0001")
PNL_DRIFT_THRESHOLD = Decimal("1.00")


@dataclass(frozen=True, slots=True)
class RefreshPositionsCommand:
    """Input to RefreshPositions."""

    account_id: str
    correlation_id: UUID
    actor: str  # who/what initiated: "scheduler", "user", "agent"


@dataclass(frozen=True, slots=True)
class RefreshPositionsResult:
    """Output from RefreshPositions."""

    account_id: str
    refreshed_positions: tuple[Position, ...]
    drift_detected: bool
    drift_details: tuple[str, ...]
    refreshed_at: datetime


async def execute(
    cmd: RefreshPositionsCommand,
    broker: BrokerPort,
    uow: UnitOfWork,
) -> RefreshPositionsResult:
    """Refresh positions for an account, emit reconciliation events.

    Steps:
    1. Read fresh positions from broker.
    2. Read prior local positions (from DB).
    3. For each: upsert local; compare to prior; record drift if material.
    4. Detect positions that vanished locally (broker no longer reports)
       or appeared (broker has, local didn't).
    5. Emit PositionReconciled per symbol; PositionDriftDetected if any drift.
    """
    now = uow.clock.now()
    session: AsyncSession = uow.session

    fresh_positions = await broker.get_positions(cmd.account_id)
    prior_positions = await _load_local_positions(session, cmd.account_id)
    prior_by_symbol = {p.symbol.ticker: p for p in prior_positions}

    drift_details: list[str] = []
    reconciled_payloads: list[DomainEvent] = []

    for pos in fresh_positions:
        await _upsert_local_position(session, pos, now)
        prior = prior_by_symbol.pop(pos.symbol.ticker, None)
        drift = _detect_drift(pos, prior)
        if drift is not None:
            kind, detail = drift
            drift_details.append(detail)
            reconciled_payloads.append(
                _make_drift_event(
                    cmd.account_id, pos.symbol, kind, pos, prior, now, cmd.correlation_id
                )
            )
        reconciled_payloads.append(_make_reconciled_event(cmd.account_id, pos, now))

    # Positions the broker no longer reports but local still has.
    for orphan_symbol, orphan_pos in prior_by_symbol.items():
        await _delete_local_position(session, cmd.account_id, orphan_symbol)
        drift_details.append(
            f"{orphan_symbol}: broker no longer reports (local had qty={orphan_pos.quantity})"
        )
        reconciled_payloads.append(
            _make_drift_event(
                cmd.account_id,
                orphan_pos.symbol,
                DriftKind.MISSING_BROKER,
                orphan_pos,
                orphan_pos,
                now,
                cmd.correlation_id,
            )
        )

    if drift_details:
        uow.collect(*reconciled_payloads)
    else:
        # Still emit reconciled events so we have a record even when no drift.
        uow.collect(*reconciled_payloads)

    return RefreshPositionsResult(
        account_id=cmd.account_id,
        refreshed_positions=fresh_positions,
        drift_detected=bool(drift_details),
        drift_details=tuple(drift_details),
        refreshed_at=now,
    )


# --- Helpers -----------------------------------------------------------------


async def _load_local_positions(session: AsyncSession, account_id: str) -> tuple[Position, ...]:
    """Read prior local positions. Empty if account is new."""
    rows = await session.stream(
        PositionRow.__table__.select().where(PositionRow.account_id == account_id)
    )
    positions: list[Position] = []
    async for row in rows:
        positions.append(
            Position(
                account_id=row.account_id,
                symbol=Symbol(row.symbol),
                quantity=row.quantity,
                average_cost=_row_money(row.average_cost, row.average_cost_currency),
                market_value=_row_money(row.market_value, "USD"),
                unrealized_pnl=_row_money(row.unrealized_pnl, "USD"),
                as_of=row.as_of,
            )
        )
    return tuple(positions)


async def _upsert_local_position(session: AsyncSession, pos: Position, now: datetime) -> None:
    """Upsert a position row. Replaces any prior row for (account, symbol)."""
    # Delete-then-insert keeps the logic simple; SA upsert with composite
    # unique is awkward and we're not perf-sensitive here.
    await session.execute(
        delete(PositionRow).where(
            PositionRow.account_id == pos.account_id,
            PositionRow.symbol == pos.symbol.ticker,
        )
    )
    session.add(
        PositionRow(
            account_id=pos.account_id,
            symbol=pos.symbol.ticker,
            asset_class=pos.symbol.asset_class.name,
            quantity=pos.quantity,
            average_cost=pos.average_cost.amount,
            average_cost_currency=pos.average_cost.currency,
            market_value=pos.market_value.amount,
            unrealized_pnl=pos.unrealized_pnl.amount,
            as_of=now,
        )
    )


async def _delete_local_position(session: AsyncSession, account_id: str, symbol: str) -> None:
    await session.execute(
        delete(PositionRow).where(
            PositionRow.account_id == account_id,
            PositionRow.symbol == symbol,
        )
    )


def _detect_drift(fresh: Position, prior: Position | None) -> tuple[DriftKind, str] | None:
    """Return (kind, human detail) if drift exceeds thresholds; else None."""
    if prior is None:
        return (
            DriftKind.MISSING_LOCAL,
            f"{fresh.symbol.ticker}: new position (qty={fresh.quantity})",
        )

    qty_diff = abs(fresh.quantity - prior.quantity)
    if qty_diff > QUANTITY_DRIFT_EPSILON:
        return (
            DriftKind.QUANTITY,
            f"{fresh.symbol.ticker}: qty {prior.quantity} -> {fresh.quantity}",
        )

    pnl_diff = abs(fresh.unrealized_pnl.amount - prior.unrealized_pnl.amount)
    if pnl_diff > PNL_DRIFT_THRESHOLD:
        return (
            DriftKind.COST_BASIS,
            f"{fresh.symbol.ticker}: pnl {prior.unrealized_pnl.amount} -> {fresh.unrealized_pnl.amount}",
        )

    return None


def _make_reconciled_event(account_id: str, pos: Position, now: datetime) -> DomainEvent:
    return DomainEvent(
        type=EventType.POSITION_RECONCILED,
        aggregate_id=f"{account_id}:{pos.symbol.ticker}",
        aggregate_type=AggregateType.POSITION,
        payload={
            "account_id": account_id,
            "symbol": pos.symbol.ticker,
            "quantity": str(pos.quantity),
            "average_cost": str(pos.average_cost.amount),
            "market_value": str(pos.market_value.amount),
            "unrealized_pnl": str(pos.unrealized_pnl.amount),
            "as_of": now.isoformat(),
        },
    )


def _make_drift_event(
    account_id: str,
    symbol: Symbol,
    kind: DriftKind,
    fresh: Position,
    prior: Position | None,
    now: datetime,
    correlation_id: UUID,
) -> DomainEvent:
    severity = Severity.CRITICAL if kind in (DriftKind.MISSING_BROKER,) else Severity.WARNING
    return DomainEvent(
        type=EventType.POSITION_DRIFT_DETECTED,
        aggregate_id=f"{account_id}:{symbol.ticker}",
        aggregate_type=AggregateType.POSITION,
        payload={
            "account_id": account_id,
            "symbol": symbol.ticker,
            "drift_kind": kind.name,
            "severity": severity.name,
            "fresh_quantity": str(fresh.quantity) if fresh else None,
            "prior_quantity": str(prior.quantity) if prior else None,
            "detected_at": now.isoformat(),
            "correlation_id": str(correlation_id),
        },
    )


def _row_money(amount: Decimal, currency: str) -> Money:
    return Money(amount=amount, currency=currency)


__all__ = [
    "RefreshPositionsCommand",
    "RefreshPositionsResult",
    "execute",
    "QUANTITY_DRIFT_EPSILON",
    "PNL_DRIFT_THRESHOLD",
]
