"""Portfolio routes.

The only route in chunk 7: GET /portfolio/{account_id} returns the current
account snapshot from the broker. POST /portfolio/{account_id}/refresh
triggers RefreshPositions (which writes to DB + emits outbox events).

No trading endpoints. The contract test in tests/apps/api/ asserts that.
"""
from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, status

from apps.common.composition import Composition, session_factory
from trading.application.common.unit_of_work import UnitOfWork
from trading.application.portfolio.refresh_positions import (
    RefreshPositionsCommand,
)
from trading.application.portfolio.refresh_positions import (
    execute as refresh_positions,
)
from trading.domain import Account

router = APIRouter()


@router.get("/{account_id}")
async def get_account(account_id: str, request: Request) -> dict[str, object]:
    """Return the current account snapshot from the broker."""
    comp: Composition = request.app.state.composition
    try:
        account = await comp.broker.get_account(account_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown account: {account_id}",
        ) from None
    return _account_to_dict(account)


@router.post("/{account_id}/refresh", status_code=status.HTTP_200_OK)
async def refresh(account_id: str, request: Request) -> dict[str, object]:
    """Refresh positions for an account. Writes to DB + emits outbox events.

    Requires DATABASE_URL to be configured. If using FakeBroker without
    DB, this returns 503 (the use case needs persistence).
    """
    comp: Composition = request.app.state.composition
    if comp.engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DATABASE_URL not configured; refresh requires persistence.",
        )

    async with session_factory(comp) as session:
        uow = UnitOfWork(
            session=session,
            clock=comp.clock,
            correlation_id=uuid4(),
        )
        async with uow:
            try:
                result = await refresh_positions(
                    RefreshPositionsCommand(
                        account_id=account_id,
                        correlation_id=uow.correlation_id,
                        actor="api",
                    ),
                    broker=comp.broker,
                    uow=uow,
                )
            except KeyError:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Unknown account: {account_id}",
                ) from None

    return {
        "account_id": result.account_id,
        "refreshed_positions_count": len(result.refreshed_positions),
        "drift_detected": result.drift_detected,
        "drift_details": list(result.drift_details),
        "refreshed_at": result.refreshed_at.isoformat(),
    }


def _account_to_dict(account: Account) -> dict[str, object]:
    """Convert an Account to a JSON-safe dict (camelCase for frontend)."""
    return {
        "accountId": account.account_id,
        "cash": str(account.cash.amount),
        "cashCurrency": account.cash.currency,
        "marketValue": str(account.market_value.amount),
        "netLiquidation": str(account.net_liquidation.amount),
        "buyingPower": str(account.buying_power.amount),
        "asOf": account.as_of.isoformat() if account.as_of else None,
        "positions": [
            {
                "symbol": p.symbol.ticker,
                "assetClass": p.symbol.asset_class.name,
                "quantity": str(p.quantity),
                "averageCost": str(p.average_cost.amount),
                "marketValue": str(p.market_value.amount),
                "unrealizedPnl": str(p.unrealized_pnl.amount),
            }
            for p in account.positions
        ],
    }

