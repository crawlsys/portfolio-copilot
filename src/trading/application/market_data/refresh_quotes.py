"""MarketDataPort + RefreshQuotes use case."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from trading.domain import Bar, Money, Position, Quote, Symbol

if TYPE_CHECKING:
    from trading.application.common.clock import ClockPort


@runtime_checkable
class MarketDataPort(Protocol):
    async def get_quote(self, symbol: Symbol) -> Quote: ...
    async def get_quotes(self, symbols: tuple[Symbol, ...]) -> tuple[Quote, ...]: ...
    async def get_bars(
        self,
        symbol: Symbol,
        timeframe: str,
        start: datetime,
        end: datetime | None = None,
    ) -> tuple[Bar, ...]: ...
    async def get_vix(self) -> Decimal: ...


class NoMarketData:
    async def get_quote(self, symbol: Symbol) -> Quote:
        raise KeyError(f"No market data for {symbol.ticker}")

    async def get_quotes(self, symbols: tuple[Symbol, ...]) -> tuple[Quote, ...]:
        return ()

    async def get_bars(
        self,
        symbol: Symbol,
        timeframe: str,
        start: datetime,
        end: datetime | None = None,
    ) -> tuple[Bar, ...]:
        return ()

    async def get_vix(self) -> Decimal:
        return Decimal("0")


@dataclass(frozen=True, slots=True)
class QuoteEnrichment:
    symbol: str
    quantity: Decimal
    cost_basis_per_share: Money
    live_price: Money | None
    live_market_value: Money | None
    live_unrealized_pnl: Money | None
    price_change_pct: Decimal | None
    quote_time: datetime | None


@dataclass(frozen=True, slots=True)
class RefreshQuotesResult:
    account_id: str
    enriched: tuple[QuoteEnrichment, ...]
    quotes_fetched: int
    quotes_missing: int
    refreshed_at: datetime


async def refresh_quotes(
    account_id: str,
    positions: tuple[Position, ...],
    market_data: MarketDataPort,
    clock: ClockPort,
) -> RefreshQuotesResult:
    now = clock.now()
    if not positions:
        return RefreshQuotesResult(account_id, (), 0, 0, now)

    # Reuse each position's existing Symbol (which already carries the correct
    # asset_class) rather than reconstructing it as EQUITY — rebuilding would
    # re-reject CUSIP fixed-income tickers and 500 the whole live refresh.
    symbols = tuple(p.symbol for p in positions if p.symbol.ticker)
    quotes = await market_data.get_quotes(symbols)
    quote_map = {q.symbol.ticker: q for q in quotes}

    enriched: list[QuoteEnrichment] = []
    fetched = 0
    missing = 0

    for pos in positions:
        q = quote_map.get(pos.symbol.ticker)
        last = q.last if (q is not None and q.last is not None) else None
        # Sub-penny prices (e.g. worthless OTC at 0.000001) exceed Money's 4-dp
        # precision and would blow up its construction. Quantize only those
        # (a worthless price rounds to 0 and is dropped below), leaving normal
        # prices — and their display formatting — untouched.
        if last is not None:
            rounded = last.quantize(Decimal("0.0001"))
            if rounded != last:
                last = rounded
        # A zero/None last price is not a usable quote — Massive's snapshot
        # endpoint returns last=0 for every ticker when the market is closed
        # (pre-/post-market). Treat it as missing so the position keeps its
        # last-known (snapshot) market value instead of collapsing to $0.
        if q is None or last is None or last <= 0:
            missing += 1
            enriched.append(
                QuoteEnrichment(
                    symbol=pos.symbol.ticker,
                    quantity=pos.quantity,
                    cost_basis_per_share=pos.average_cost,
                    live_price=None,
                    live_market_value=None,
                    live_unrealized_pnl=None,
                    price_change_pct=None,
                    quote_time=None,
                )
            )
            continue

        fetched += 1
        live_price = Money(amount=last, currency=pos.market_value.currency)
        live_mv = Money(
            amount=(last * pos.quantity).quantize(Decimal("0.0001")),
            currency=pos.market_value.currency,
        )
        cost_total = pos.average_cost.amount * pos.quantity
        live_pnl = Money(
            amount=(live_mv.amount - cost_total).quantize(Decimal("0.0001")),
            currency=pos.market_value.currency,
        )
        pct = (
            ((last - pos.average_cost.amount) / pos.average_cost.amount * 100)
            if pos.average_cost.amount
            else Decimal("0")
        ).quantize(Decimal("0.01"))
        enriched.append(
            QuoteEnrichment(
                symbol=pos.symbol.ticker,
                quantity=pos.quantity,
                cost_basis_per_share=pos.average_cost,
                live_price=live_price,
                live_market_value=live_mv,
                live_unrealized_pnl=live_pnl,
                price_change_pct=pct,
                quote_time=q.timestamp,
            )
        )

    return RefreshQuotesResult(account_id, tuple(enriched), fetched, missing, now)


__all__ = [
    "MarketDataPort",
    "NoMarketData",
    "QuoteEnrichment",
    "RefreshQuotesResult",
    "refresh_quotes",
]
