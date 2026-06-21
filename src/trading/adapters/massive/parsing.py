"""Pure Massive JSON parsers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading.domain import Bar, Quote, Symbol

JsonObject = dict[str, object]

_TIMEFRAME_PARTS: dict[str, tuple[int, str, timedelta]] = {
    "1m": (1, "minute", timedelta(minutes=1)),
    "5m": (5, "minute", timedelta(minutes=5)),
    "15m": (15, "minute", timedelta(minutes=15)),
    "30m": (30, "minute", timedelta(minutes=30)),
    "1h": (1, "hour", timedelta(hours=1)),
    "4h": (4, "hour", timedelta(hours=4)),
    "1d": (1, "day", timedelta(days=1)),
    "1w": (1, "week", timedelta(weeks=1)),
}


def parse_quote_snapshot(payload: Mapping[str, object], symbol: Symbol) -> Quote:
    """Parse a single-ticker snapshot response into a domain Quote."""

    ticker_payload = _mapping(payload.get("ticker"), "ticker")
    return parse_snapshot_ticker(ticker_payload, symbol)


def parse_snapshot_ticker(payload: Mapping[str, object], symbol: Symbol | None = None) -> Quote:
    """Parse one item from Massive's stock snapshot endpoints."""

    ticker = _str(payload.get("ticker"), "ticker")
    quote_symbol = symbol or Symbol(ticker)
    quote = _mapping(payload.get("lastQuote"), "lastQuote")
    trade = _optional_mapping(payload.get("lastTrade"))
    day = _optional_mapping(payload.get("day"))

    bid = _decimal(quote.get("p"), "lastQuote.p")
    ask = _decimal(quote.get("P"), "lastQuote.P")
    last = _decimal(trade.get("p"), "lastTrade.p") if trade is not None else (bid + ask) / 2

    timestamp_ns = _optional_int(quote.get("t"))
    if trade is not None:
        trade_ts = _optional_int(trade.get("t"))
        if trade_ts is not None and (timestamp_ns is None or trade_ts > timestamp_ns):
            timestamp_ns = trade_ts
    if timestamp_ns is None:
        timestamp_ns = _int(payload.get("updated"), "updated")

    volume = _optional_int(day.get("v")) if day is not None else None
    return Quote(
        symbol=quote_symbol,
        bid=bid,
        ask=ask,
        last=last,
        timestamp=_from_unix_ns(timestamp_ns),
        volume=volume,
    )


def parse_snapshot_quotes(
    payload: Mapping[str, object], symbols: tuple[Symbol, ...]
) -> tuple[Quote, ...]:
    """Parse Massive's full-market snapshot response filtered by requested symbols."""

    symbol_by_ticker = {symbol.ticker: symbol for symbol in symbols}
    tickers = _sequence(payload.get("tickers"), "tickers")
    quotes: list[Quote] = []
    for item in tickers:
        ticker_payload = _mapping(item, "tickers[]")
        ticker = _str(ticker_payload.get("ticker"), "tickers[].ticker")
        if ticker in symbol_by_ticker:
            quotes.append(parse_snapshot_ticker(ticker_payload, symbol_by_ticker[ticker]))
    return tuple(quotes)


def parse_bars(payload: Mapping[str, object], symbol: Symbol, timeframe: str) -> tuple[Bar, ...]:
    """Parse aggregate bars into domain Bars."""

    _, _, duration = timeframe_to_massive(timeframe)
    rows = _sequence(payload.get("results", ()), "results")
    bars: list[Bar] = []
    for row in rows:
        item = _mapping(row, "results[]")
        opened_at = _from_unix_ms(_int(item.get("t"), "results[].t"))
        bars.append(
            Bar(
                symbol=symbol,
                open=_decimal(item.get("o"), "results[].o"),
                high=_decimal(item.get("h"), "results[].h"),
                low=_decimal(item.get("l"), "results[].l"),
                close=_decimal(item.get("c"), "results[].c"),
                volume=_int(item.get("v"), "results[].v"),
                opened_at=opened_at,
                closed_at=opened_at + duration,
                timeframe=timeframe,
                vwap=_optional_decimal(item.get("vw")),
            )
        )
    return tuple(bars)


def parse_ticker_results(payload: Mapping[str, object]) -> tuple[dict[str, object], ...]:
    """Return ticker search results as immutable-ish raw dictionaries."""

    return tuple(
        dict(_mapping(item, "results[]")) for item in _sequence(payload.get("results"), "results")
    )


def timeframe_to_massive(timeframe: str) -> tuple[int, str, timedelta]:
    """Map local timeframe strings to Massive aggregate path parts."""

    if timeframe not in _TIMEFRAME_PARTS:
        raise ValueError(f"Unsupported Massive timeframe: {timeframe!r}")
    return _TIMEFRAME_PARTS[timeframe]


def _from_unix_ns(value: int) -> datetime:
    seconds, nanos = divmod(value, 1_000_000_000)
    return datetime.fromtimestamp(seconds, tz=UTC) + timedelta(microseconds=nanos // 1000)


def _from_unix_ms(value: int) -> datetime:
    seconds, millis = divmod(value, 1000)
    return datetime.fromtimestamp(seconds, tz=UTC) + timedelta(milliseconds=millis)


def _decimal(value: object, field: str) -> Decimal:
    if value is None:
        raise ValueError(f"Missing Massive field: {field}")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | str):
        return Decimal(str(value))
    raise TypeError(
        f"Massive field {field} must be Decimal, int, or str; got {type(value).__name__}"
    )


def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, "optional decimal")


def _int(value: object, field: str) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"Missing Massive integer field: {field}")
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return int(value)
    if isinstance(value, str):
        return int(Decimal(value))
    raise TypeError(f"Massive field {field} must be int-like; got {type(value).__name__}")


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _int(value, "optional integer")


def _str(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"Massive field {field} must be str; got {type(value).__name__}")
    return value


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"Massive field {field} must be object; got {type(value).__name__}")
    return value


def _optional_mapping(value: object) -> Mapping[str, object] | None:
    if value is None:
        return None
    return _mapping(value, "optional object")


def _sequence(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise TypeError(f"Massive field {field} must be array; got {type(value).__name__}")
    return value
