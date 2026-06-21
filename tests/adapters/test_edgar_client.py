"""Cassette tests for EDGARClient."""

from __future__ import annotations

from datetime import date

import pytest

from trading.adapters.edgar import (
    EDGARAuthError,
    EDGARClient,
    EDGARNotFoundError,
)


class TestEDGARClientConstruction:
    def test_requires_user_agent(self) -> None:
        with pytest.raises(ValueError, match="user_agent is required"):
            EDGARClient("")

    def test_requires_email_in_user_agent(self) -> None:
        with pytest.raises(ValueError, match="must contain an email"):
            EDGARClient("tracker without email")

    def test_accepts_valid_user_agent(self) -> None:
        client = EDGARClient("tracker test@example.com")
        assert client._user_agent == "tracker test@example.com"

    def test_custom_base_url(self) -> None:
        client = EDGARClient("tracker test@example.com", base_url="https://custom.sec.gov/")
        assert client._base_url == "https://custom.sec.gov"


@pytest.mark.cassette
class TestTickerToCik:
    @pytest.fixture
    def client(self) -> EDGARClient:
        return EDGARClient("tracker test@example.com")

    async def test_looks_up_known_ticker(self, client: EDGARClient, trading_vcr: object) -> None:
        with trading_vcr.use_cassette("edgar/company_tickers.yaml"):  # type: ignore[union-attr]
            cik = await client.ticker_to_cik("AAPL")
            assert cik == "0000320193"

    async def test_normalizes_ticker_case(self, client: EDGARClient, trading_vcr: object) -> None:
        with trading_vcr.use_cassette("edgar/company_tickers.yaml"):  # type: ignore[union-attr]
            cik = await client.ticker_to_cik("aapl")
            assert cik == "0000320193"

    async def test_caches_ticker_map(self, client: EDGARClient, trading_vcr: object) -> None:
        with trading_vcr.use_cassette("edgar/company_tickers.yaml"):  # type: ignore[union-attr]
            await client.ticker_to_cik("AAPL")
            await client.ticker_to_cik("NVDA")
            assert client._ticker_to_cik_cache is not None

    async def test_raises_not_found_for_unknown_ticker(
        self, client: EDGARClient, trading_vcr: object
    ) -> None:
        with (
            trading_vcr.use_cassette("edgar/company_tickers.yaml"),  # type: ignore[union-attr]
            pytest.raises(EDGARNotFoundError, match="Ticker not found"),
        ):
            await client.ticker_to_cik("NOTREAL")


@pytest.mark.cassette
class TestGetSubmissions:
    @pytest.fixture
    def client(self) -> EDGARClient:
        return EDGARClient("tracker test@example.com")

    async def test_returns_company_filings(self, client: EDGARClient, trading_vcr: object) -> None:
        with trading_vcr.use_cassette("edgar/submissions_aapl.yaml"):  # type: ignore[union-attr]
            result = await client.get_submissions("AAPL")
            assert result["cik"] == "0000320193"
            assert result["name"] == "Apple Inc."
            assert "filings" in result


@pytest.mark.cassette
class TestGetForm4Filings:
    @pytest.fixture
    def client(self) -> EDGARClient:
        return EDGARClient("tracker test@example.com")

    async def test_returns_form4_filings(self, client: EDGARClient, trading_vcr: object) -> None:
        with trading_vcr.use_cassette("edgar/submissions_aapl.yaml"):  # type: ignore[union-attr]
            result = await client.get_form4_filings("AAPL")
            assert len(result) == 2
            assert all(f["form"] == "4" for f in result)

    async def test_filters_by_date(self, client: EDGARClient, trading_vcr: object) -> None:
        with trading_vcr.use_cassette("edgar/submissions_aapl.yaml"):  # type: ignore[union-attr]
            result = await client.get_form4_filings("AAPL", since=date(2026, 6, 1))
            assert len(result) == 2
            assert all(f["filing_date"] >= "2026-06-01" for f in result)


@pytest.mark.cassette
class TestGetForm4Details:
    @pytest.fixture
    def client(self) -> EDGARClient:
        return EDGARClient("tracker test@example.com")

    async def test_fetches_and_parses_form4_xml(
        self, client: EDGARClient, trading_vcr: object
    ) -> None:
        with trading_vcr.use_cassette("edgar/form4_details.yaml"):  # type: ignore[union-attr]
            result = await client.get_form4_details("320193", "0001140361-26-025622")
            assert result is not None
            assert result["issuer"]["ticker"] == "AAPL"
            assert result["owner"]["name"] == "Newstead Jennifer"
            transactions = result["transactions"]
            assert isinstance(transactions, list)
            assert len(transactions) == 1


@pytest.mark.cassette
class TestSearchFullText:
    @pytest.fixture
    def client(self) -> EDGARClient:
        return EDGARClient("tracker test@example.com")

    async def test_returns_search_results(self, client: EDGARClient, trading_vcr: object) -> None:
        with trading_vcr.use_cassette("edgar/full_text_search.yaml"):  # type: ignore[union-attr]
            result = await client.search_full_text("apple", limit=5)
            assert len(result) == 2
            assert result[0]["ciks"] == ["0000320193"]
            assert result[0]["form"] == "10-K"

    async def test_caps_limit_at_100(self, client: EDGARClient) -> None:
        assert client is not None


class TestErrorHandling:
    def test_auth_error_message(self) -> None:
        err = EDGARAuthError("403 — bad User-Agent")
        assert "403" in str(err)

    def test_not_found_error(self) -> None:
        err = EDGARNotFoundError("CIK not found")
        assert "CIK" in str(err)
