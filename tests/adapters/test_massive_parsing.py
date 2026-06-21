from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from trading.adapters.massive.parsing import parse_bars, parse_quote_snapshot, timeframe_to_massive
from trading.domain import Symbol


def test_parse_quote_snapshot_uses_last_trade_for_last_price_and_day_volume() -> None:
    quote = parse_quote_snapshot(
        {
            "status": "OK",
            "ticker": {
                "ticker": "AAPL",
                "lastQuote": {
                    "p": Decimal("120.46"),
                    "P": Decimal("120.47"),
                    "t": 1605195918507251700,
                },
                "lastTrade": {"p": Decimal("120.47"), "s": 236, "t": 1605195918306274000},
                "day": {"v": 28727868},
                "updated": 1605195918306274000,
            },
        },
        Symbol("AAPL"),
    )

    assert quote.symbol == Symbol("AAPL")
    assert quote.bid == Decimal("120.46")
    assert quote.ask == Decimal("120.47")
    assert quote.last == Decimal("120.47")
    assert quote.volume == 28727868
    assert quote.timestamp == datetime(2020, 11, 12, 15, 45, 18, 507251, tzinfo=UTC)


def test_parse_quote_snapshot_falls_back_to_midpoint_without_last_trade() -> None:
    quote = parse_quote_snapshot(
        {
            "status": "OK",
            "ticker": {
                "ticker": "MSFT",
                "lastQuote": {
                    "p": Decimal("420.10"),
                    "P": Decimal("420.14"),
                    "t": 1605195918507251700,
                },
                "updated": 1605195918507251700,
            },
        },
        Symbol("MSFT"),
    )

    assert quote.last == Decimal("420.12")
    assert quote.volume is None


def test_parse_bars_maps_ohlcv_and_closes_at_timeframe_boundary() -> None:
    bars = parse_bars(
        {
            "ticker": "AAPL",
            "results": [
                {
                    "o": Decimal("74.06"),
                    "h": Decimal("75.15"),
                    "l": Decimal("73.7975"),
                    "c": Decimal("75.0875"),
                    "v": 135647456,
                    "vw": Decimal("74.6099"),
                    "t": 1577941200000,
                }
            ],
            "status": "OK",
        },
        Symbol("AAPL"),
        "1d",
    )

    assert len(bars) == 1
    assert bars[0].open == Decimal("74.06")
    assert bars[0].close == Decimal("75.0875")
    assert bars[0].vwap == Decimal("74.6099")
    assert bars[0].opened_at == datetime(2020, 1, 2, 5, 0, tzinfo=UTC)
    assert bars[0].closed_at == bars[0].opened_at + timedelta(days=1)


def test_timeframe_to_massive_rejects_unknown_timeframe() -> None:
    try:
        timeframe_to_massive("2x")
    except ValueError as exc:
        assert "Unsupported Massive timeframe" in str(exc)
    else:
        raise AssertionError("expected ValueError")


@given(
    value=st.decimals(
        min_value=Decimal("0.0001"),
        max_value=Decimal("999999.9999"),
        places=4,
        allow_nan=False,
        allow_infinity=False,
    )
)
def test_quote_parser_preserves_decimal_precision(value: Decimal) -> None:
    quote = parse_quote_snapshot(
        {
            "status": "OK",
            "ticker": {
                "ticker": "AAPL",
                "lastQuote": {"p": value, "P": value + Decimal("0.0001"), "t": 1605195918507251700},
                "lastTrade": {"p": value, "t": 1605195918507251700},
                "updated": 1605195918507251700,
            },
        },
        Symbol("AAPL"),
    )

    assert quote.bid == value
    assert quote.last == value
