from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal

from apps.api.app import create_app
from apps.common.composition import Composition
from fastapi.testclient import TestClient

from trading.adapters.fake.broker import FakeBroker
from trading.adapters.notifications import LoggingNotifier
from trading.application.common.clock import FrozenClock
from trading.application.common.event_bus import EventBus
from trading.application.market_data.refresh_quotes import NoMarketData
from trading.domain import AccountType, Bar, Money, Quote, Symbol

ACCOUNT_ID = "paper-live"


def test_portfolio_without_live_query_returns_snapshot_only() -> None:
    market_data = FakeMarketData(
        {
            "AAPL": Quote(
                symbol=Symbol("AAPL"),
                bid=Decimal("119.50"),
                ask=Decimal("120.50"),
                last=Decimal("120.00"),
                timestamp=datetime(2026, 6, 22, 15, 30, tzinfo=UTC),
            )
        }
    )
    with _client(market_data=market_data) as client:
        response = client.get(f"/portfolio/{ACCOUNT_ID}")

    assert response.status_code == 200
    body = response.json()
    assert "liveNetLiquidation" not in body
    assert "liveDayPnl" not in body
    assert "livePrice" not in body["positions"][0]


def test_portfolio_live_query_with_no_market_data_returns_snapshot_only() -> None:
    with _client(market_data=NoMarketData()) as client:
        response = client.get(f"/portfolio/{ACCOUNT_ID}?live=true")

    assert response.status_code == 200
    body = response.json()
    assert "liveNetLiquidation" not in body
    assert "liveDayPnl" not in body
    assert "livePrice" not in body["positions"][0]


def test_portfolio_live_query_with_market_data_returns_enriched_snapshot() -> None:
    quote_time = datetime(2026, 6, 22, 15, 30, tzinfo=UTC)
    market_data = FakeMarketData(
        {
            "AAPL": Quote(
                symbol=Symbol("AAPL"),
                bid=Decimal("119.50"),
                ask=Decimal("120.50"),
                last=Decimal("120.00"),
                timestamp=quote_time,
            )
        }
    )

    with _client(market_data=market_data) as client:
        response = client.get(f"/portfolio/{ACCOUNT_ID}?live=true")

    assert response.status_code == 200
    body = response.json()
    assert body["liveNetLiquidation"] == "2200.0000"
    assert body["liveDayPnl"] == "100.0000"

    position = body["positions"][0]
    assert position["livePrice"] == "120.00"
    assert position["liveMarketValue"] == "1200.0000"
    assert position["liveUnrealizedPnl"] == "200.0000"
    assert position["priceChangePct"] == "20.00"
    assert position["quoteTime"] == quote_time.isoformat()


def test_portfolio_live_zero_price_quote_falls_back_to_snapshot() -> None:
    """Market closed: Massive returns last=0 for every ticker. The live total
    must keep the snapshot market value, not collapse the position to $0."""
    market_data = FakeMarketData(
        {
            "AAPL": Quote(
                symbol=Symbol("AAPL"),
                bid=Decimal("0"),
                ask=Decimal("0"),
                last=Decimal("0"),
                timestamp=datetime(2026, 6, 22, 5, 0, tzinfo=UTC),
            )
        }
    )

    with _client(market_data=market_data) as client:
        response = client.get(f"/portfolio/{ACCOUNT_ID}?live=true")

    assert response.status_code == 200
    body = response.json()
    # Core guard: a zero-price quote must NOT zero the position's live value.
    position = body["positions"][0]
    assert position["livePrice"] is None
    assert position["liveMarketValue"] is None
    # With no usable quotes, no live total is published — the snapshot
    # netLiquidation (cash 1000 + mv 1100 = 2100) stands, not a collapsed total.
    assert "liveNetLiquidation" not in body
    assert body["netLiquidation"] == "2100.00"


class FakeMarketData:
    def __init__(self, quotes: dict[str, Quote]) -> None:
        self._quotes = quotes

    async def get_quote(self, symbol: Symbol) -> Quote:
        quote = self._quotes.get(symbol.ticker)
        if quote is None:
            raise KeyError(f"No quote for {symbol.ticker}")
        return quote

    async def get_quotes(self, symbols: tuple[Symbol, ...]) -> tuple[Quote, ...]:
        return tuple(
            quote for symbol in symbols if (quote := self._quotes.get(symbol.ticker)) is not None
        )

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


@contextmanager
def _client(market_data: object) -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as client:
        client.app.state.composition = Composition(
            broker=_broker(),
            clock=FrozenClock(datetime(2026, 6, 22, 16, 0, tzinfo=UTC)),
            bus=EventBus(),
            engine=None,
            blob_store=None,
            notifier=LoggingNotifier(),
            market_data=market_data,
        )
        yield client


def _broker() -> FakeBroker:
    broker = FakeBroker()
    broker.add_account(
        account_id=ACCOUNT_ID,
        nickname="Live Test",
        masked_schwab_id="****9999",
        account_type=AccountType.MARGIN,
        margin_enabled=True,
        cash=Money.usd("1000"),
    )
    broker.set_position(
        account_id=ACCOUNT_ID,
        symbol=Symbol("AAPL"),
        quantity=Decimal("10"),
        average_cost=Money.usd("100.00"),
        market_value=Money.usd("1100.00"),
    )
    return broker
