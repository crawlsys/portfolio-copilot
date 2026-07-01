"""Portfolio routes.

The only route in chunk 7: GET /portfolio/{account_id} returns the current
account snapshot from the broker. POST /portfolio/{account_id}/refresh
triggers RefreshPositions (which writes to DB + emits outbox events).

No trading endpoints. The contract test in tests/apps/api/ asserts that.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, status

# ruff: noqa: N815 (camelCase keys are intentional for frontend JSON conventions)
from pydantic import BaseModel, ConfigDict

from apps.common.composition import Composition, session_factory
from trading.adapters.schwab.exceptions import SchwabAccountNotFoundError as _AccountNotFound
from trading.application.common.unit_of_work import UnitOfWork
from trading.application.market_data.refresh_quotes import (
    NoMarketData,
    QuoteEnrichment,
)
from trading.application.market_data.refresh_quotes import (
    refresh_quotes as refresh_position_quotes,
)
from trading.application.portfolio.refresh_positions import (
    RefreshPositionsCommand,
)
from trading.application.portfolio.refresh_positions import (
    execute as refresh_positions,
)
from trading.domain import Account

router = APIRouter()


class PositionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    assetClass: str
    quantity: str
    averageCost: str
    marketValue: str
    unrealizedPnl: str
    livePrice: str | None = None
    liveMarketValue: str | None = None
    liveUnrealizedPnl: str | None = None
    priceChangePct: str | None = None
    quoteTime: str | None = None


class AccountSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accountId: str
    cash: str
    cashCurrency: str
    marketValue: str
    netLiquidation: str
    liveNetLiquidation: str | None = None
    liveDayPnl: str | None = None
    buyingPower: str
    asOf: str | None
    positions: list[PositionSnapshot]


class RefreshPortfolioResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str
    refreshed_positions_count: int
    drift_detected: bool
    drift_details: list[str]
    refreshed_at: str


@router.get("/{account_id}")
async def get_account(
    account_id: str,
    request: Request,
    live: bool = Query(default=False),
) -> dict[str, object]:
    """Return the current account snapshot from the broker."""
    comp: Composition = request.app.state.composition
    try:
        account = await comp.broker.get_account(account_id)
    except (KeyError, _AccountNotFound):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown account: {account_id}",
        ) from None

    snapshot = _account_to_dict(account)
    if not live or comp.market_data is None or isinstance(comp.market_data, NoMarketData):
        return snapshot

    try:
        positions = await comp.broker.get_positions(account_id)
    except (KeyError, _AccountNotFound):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown account: {account_id}",
        ) from None

    quotes = await refresh_position_quotes(
        account_id=account_id,
        positions=positions,
        market_data=comp.market_data,
        clock=comp.clock,
    )
    _apply_quote_enrichment(snapshot, quotes.enriched)
    if quotes.quotes_fetched > 0:
        _apply_account_live_totals(snapshot, account.cash.amount)
    return snapshot


@router.post(
    "/{account_id}/refresh",
    status_code=status.HTTP_200_OK,
    response_model=RefreshPortfolioResponse,
)
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
            blob_store=comp.blob_store,
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


def _apply_quote_enrichment(
    snapshot: dict[str, object],
    enriched_quotes: tuple[QuoteEnrichment, ...],
) -> None:
    """Overlay nullable live quote fields onto position dictionaries."""
    enriched_by_symbol = {quote.symbol: quote for quote in enriched_quotes}
    positions = snapshot["positions"]
    if not isinstance(positions, list):
        return

    for position in positions:
        if not isinstance(position, dict):
            continue
        symbol = position.get("symbol")
        quote = enriched_by_symbol.get(symbol) if isinstance(symbol, str) else None
        position["livePrice"] = (
            str(quote.live_price.amount) if quote and quote.live_price is not None else None
        )
        position["liveMarketValue"] = (
            str(quote.live_market_value.amount)
            if quote and quote.live_market_value is not None
            else None
        )
        position["liveUnrealizedPnl"] = (
            str(quote.live_unrealized_pnl.amount)
            if quote and quote.live_unrealized_pnl is not None
            else None
        )
        position["priceChangePct"] = (
            str(quote.price_change_pct) if quote and quote.price_change_pct is not None else None
        )
        position["quoteTime"] = quote.quote_time.isoformat() if quote and quote.quote_time else None


def _apply_account_live_totals(snapshot: dict[str, object], cash_amount: Decimal) -> None:
    """Calculate live account totals from live position values when present."""
    positions = snapshot["positions"]
    if not isinstance(positions, list):
        return

    snapshot_market_value = Decimal(str(snapshot["marketValue"]))
    live_market_value = Decimal("0")
    for position in positions:
        if not isinstance(position, dict):
            continue
        value = position.get("liveMarketValue") or position.get("marketValue") or "0"
        live_market_value += Decimal(str(value))

    live_net_liquidation = (cash_amount + live_market_value).quantize(Decimal("0.0001"))
    live_day_pnl = (live_market_value - snapshot_market_value).quantize(Decimal("0.0001"))
    snapshot["liveNetLiquidation"] = str(live_net_liquidation)
    snapshot["liveDayPnl"] = str(live_day_pnl)
