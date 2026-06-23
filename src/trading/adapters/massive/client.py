"""Async Massive.com market data adapter."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Self, cast
from urllib.parse import parse_qsl, urlparse

import httpx

from trading.adapters.massive.exceptions import (
    MassiveAuthError,
    MassiveError,
    MassiveRateLimitError,
)
from trading.adapters.massive.parsing import (
    JsonObject,
    parse_bars,
    parse_quote_snapshot,
    parse_snapshot_quotes,
    parse_ticker_results,
    timeframe_to_massive,
)
from trading.domain import Bar, Quote, Symbol

DEFAULT_BASE_URL = "https://api.massive.com"
WEBSOCKET_URL = "wss://socket.massive.com/stocks"


class MassiveClient:
    """Read-only Massive market data client.

    The underlying httpx client is created lazily so the adapter can be
    constructed in composition roots and tests without touching the network.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_quote(self, symbol: Symbol) -> Quote:
        path = f"/v2/snapshot/locale/us/markets/stocks/tickers/{symbol.ticker}"
        try:
            payload = await self._get(path)
        except MassiveError as exc:
            if getattr(exc, "status_code", None) == 404:
                raise KeyError(f"No quote for {symbol.ticker}") from exc
            raise
        try:
            return parse_quote_snapshot(payload, symbol)
        except (TypeError, ValueError) as exc:
            raise KeyError(f"No quote for {symbol.ticker}") from exc

    async def get_quotes(self, symbols: tuple[Symbol, ...]) -> tuple[Quote, ...]:
        """Batch quotes. Falls back to individual /prev calls on 403 (tier limit)."""
        if not symbols:
            return ()
        try:
            payload = await self._get(
                "/v2/snapshot/locale/us/markets/stocks/tickers",
                params={"tickers": ",".join(symbol.ticker for symbol in symbols)},
            )
            return parse_snapshot_quotes(payload, symbols)
            # Return whatever we got — missing tickers just don't get enriched.
            return parse_snapshot_quotes(payload, symbols)
        except MassiveAuthError:
            return await self._fan_out_prev_quotes(symbols)

    async def _fan_out_prev_quotes(self, symbols: tuple[Symbol, ...]) -> tuple[Quote, ...]:
        """Per-ticker /prev fallback (works on lower tiers, EOD only)."""
        results: list[Quote | None] = [None] * len(symbols)
        for i in range(0, len(symbols), 5):
            batch = symbols[i : i + 5]
            tasks = [self._fetch_prev(sym) for sym in batch]
            completed = await asyncio.gather(*tasks, return_exceptions=True)
            for j, result in enumerate(completed):
                if isinstance(result, Quote):
                    results[i + j] = result
        return tuple(r for r in results if r is not None)

    async def _fetch_prev(self, symbol: Symbol) -> Quote | None:
        """Fetch previous close via /v2/aggs/ticker/{symbol}/prev."""
        try:
            payload = await self._get(f"/v2/aggs/ticker/{symbol.ticker}/prev")
            results: list[object] = payload.get("results", [])  # type: ignore[assignment]
            if not results:
                return None
            r = results[0]
            if not isinstance(r, dict):
                return None
            close = Decimal(str(r.get("c", 0)))
            if close == 0:
                return None
            return Quote(
                symbol=symbol,
                bid=close,
                ask=close,
                last=close,
                timestamp=datetime.now(UTC),
                volume=int(r.get("v", 0)) if r.get("v") else None,
            )
        except (MassiveError, KeyError, ValueError):
            return None

    async def get_bars(
        self,
        symbol: Symbol,
        timeframe: str,
        start: datetime,
        end: datetime | None = None,
    ) -> tuple[Bar, ...]:
        multiplier, timespan, _duration = timeframe_to_massive(timeframe)
        to = end or datetime.now(UTC)
        path = (
            f"/v2/aggs/ticker/{symbol.ticker}/range/"
            f"{multiplier}/{timespan}/{_datetime_ms(start)}/{_datetime_ms(to)}"
        )
        payload = await self._get(
            path, params={"adjusted": "true", "sort": "asc", "limit": "50000"}
        )
        return parse_bars(payload, symbol, timeframe)

    async def get_option_chain(
        self, underlying: Symbol, expiration: date | None
    ) -> dict[str, object]:
        params: dict[str, str] = {"limit": "250"}
        if expiration is not None:
            params["expiration_date"] = expiration.isoformat()
        return await self._get(f"/v3/snapshot/options/{underlying.ticker}", params=params)

    async def search_tickers(self, query: str, limit: int = 10) -> tuple[dict[str, object], ...]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        payload = await self._get(
            "/v3/reference/tickers",
            params={
                "search": query,
                "market": "stocks",
                "active": "true",
                "limit": str(min(limit, 1000)),
                "sort": "ticker",
                "order": "asc",
            },
        )
        return parse_ticker_results(payload)

    async def get_vix(self) -> Decimal:
        """Get the current VIX value from the CBOE Volatility Index."""
        payload = await self._get("/v2/aggs/ticker/I:VIX/prev")
        results: list[object] = payload.get("results", [])  # type: ignore[assignment]
        if not results:
            return Decimal("0")
        first = results[0]
        if isinstance(first, dict):
            return Decimal(str(first.get("c", 0)))
        return Decimal("0")

    def websocket_stub(self) -> str:
        """Return the planned stock WebSocket URL; streaming is not implemented yet."""

        return WEBSOCKET_URL

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Accept": "application/json",
                    "User-Agent": "tracker-massive-adapter/0.1",
                },
            )
        return self._client

    async def _get(self, path: str, params: dict[str, str] | None = None) -> JsonObject:
        try:
            if path.startswith("http"):
                parsed = urlparse(path)
                path = parsed.path
                params = dict(parse_qsl(parsed.query, keep_blank_values=True))
            response = await self._http.get(path, params=params)
        except httpx.HTTPError as exc:
            raise MassiveError(f"Massive network error: {exc}") from exc

        if response.status_code in {401, 403}:
            raise MassiveAuthError(_error_message(response))
        if response.status_code == 429:
            raise MassiveRateLimitError(
                _error_message(response),
                retry_after=response.headers.get("Retry-After"),
                rate_limit=response.headers.get("X-RateLimit-Limit"),
                rate_limit_remaining=response.headers.get("X-RateLimit-Remaining"),
                rate_limit_reset=response.headers.get("X-RateLimit-Reset"),
            )
        if response.status_code >= 500:
            raise MassiveError(_error_message(response), status_code=response.status_code)
        if response.status_code >= 400:
            raise MassiveError(_error_message(response), status_code=response.status_code)

        loaded = json.loads(response.text, parse_float=Decimal)
        if not isinstance(loaded, dict):
            raise MassiveError("Massive returned a non-object JSON response")
        return cast(JsonObject, loaded)


def _datetime_ms(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return str(int(value.timestamp() * 1000))


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"Massive HTTP {response.status_code}: {response.text}"
    if isinstance(payload, dict):
        message = payload.get("error") or payload.get("message")
        if isinstance(message, str):
            return f"Massive HTTP {response.status_code}: {message}"
    return f"Massive HTTP {response.status_code}: {response.text}"
