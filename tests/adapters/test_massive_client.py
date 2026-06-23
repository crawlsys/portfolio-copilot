from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
import vcr as vcr_module

from trading.adapters.massive.client import MassiveClient
from trading.adapters.massive.exceptions import MassiveAuthError, MassiveRateLimitError
from trading.domain import Symbol


@pytest.mark.cassette
async def test_get_quote_uses_single_ticker_snapshot(trading_vcr: vcr_module.VCR) -> None:
    client = MassiveClient(api_key="dummy")
    with trading_vcr.use_cassette("massive/get_quote_AAPL.yaml"):
        quote = await client.get_quote(Symbol("AAPL"))
    await client.aclose()

    assert quote.symbol == Symbol("AAPL")
    assert quote.bid == Decimal("120.46")
    assert quote.ask == Decimal("120.47")
    assert quote.last == Decimal("120.47")
    assert quote.volume == 28727868


@pytest.mark.cassette
async def test_get_quotes_uses_batch_snapshot(trading_vcr: vcr_module.VCR) -> None:
    client = MassiveClient(api_key="dummy")
    with trading_vcr.use_cassette("massive/get_quotes_AAPL_MSFT.yaml"):
        quotes = await client.get_quotes((Symbol("AAPL"), Symbol("MSFT")))
    await client.aclose()

    assert [quote.symbol.ticker for quote in quotes] == ["AAPL", "MSFT"]
    assert quotes[1].last == Decimal("420.11")


@pytest.mark.cassette
async def test_get_bars(trading_vcr: vcr_module.VCR) -> None:
    client = MassiveClient(api_key="dummy")
    with trading_vcr.use_cassette("massive/get_bars_AAPL.yaml"):
        bars = await client.get_bars(
            Symbol("AAPL"),
            "1d",
            datetime(2020, 1, 2, tzinfo=UTC),
            datetime(2020, 1, 4, tzinfo=UTC),
        )
    await client.aclose()

    assert len(bars) == 2
    assert bars[0].open == Decimal("74.06")
    assert bars[1].close == Decimal("74.3575")


@pytest.mark.cassette
async def test_get_option_chain_returns_raw_payload(trading_vcr: vcr_module.VCR) -> None:
    client = MassiveClient(api_key="dummy")
    with trading_vcr.use_cassette("massive/get_option_chain_AAPL.yaml"):
        chain = await client.get_option_chain(Symbol("AAPL"), date(2022, 1, 21))
    await client.aclose()

    assert chain["status"] == "OK"
    results = chain["results"]
    assert isinstance(results, list)
    assert results[0]["details"]["ticker"] == "O:AAPL220121C00150000"


@pytest.mark.cassette
async def test_search_tickers(trading_vcr: vcr_module.VCR) -> None:
    client = MassiveClient(api_key="dummy")
    with trading_vcr.use_cassette("massive/search_tickers_apple.yaml"):
        results = await client.search_tickers("apple", limit=2)
    await client.aclose()

    assert results[0]["ticker"] == "AAPL"
    assert results[0]["name"] == "Apple Inc."


@pytest.mark.cassette
async def test_auth_error_maps_401(trading_vcr: vcr_module.VCR) -> None:
    client = MassiveClient(api_key="dummy")
    with trading_vcr.use_cassette("massive/auth_error.yaml"), pytest.raises(MassiveAuthError):
        await client.search_tickers("apple")
    await client.aclose()


@pytest.mark.cassette
async def test_rate_limit_error_includes_retry_after(trading_vcr: vcr_module.VCR) -> None:
    client = MassiveClient(api_key="dummy")
    with (
        trading_vcr.use_cassette("massive/rate_limit.yaml"),
        pytest.raises(MassiveRateLimitError) as exc_info,
    ):
        await client.search_tickers("apple")
    await client.aclose()

    assert exc_info.value.retry_after == "30"
    assert exc_info.value.rate_limit_remaining == "0"


async def test_get_vix_soft_fails_on_auth_error() -> None:
    """VIX is an index; Starter tier isn't entitled → 403.

    get_vix should return Decimal("0") rather than raising, so the VIX
    alert job and briefing regime don't spam the logs every cycle.
    """
    client = MassiveClient(api_key="dummy")

    async def _raise_auth(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise MassiveAuthError("Massive HTTP 403: not entitled to this data")

    client._get = _raise_auth  # type: ignore[method-assign]
    vix = await client.get_vix()
    await client.aclose()

    assert vix == Decimal("0")
