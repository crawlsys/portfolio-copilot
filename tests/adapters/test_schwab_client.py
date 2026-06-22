"""Cassette-based tests for SchwabBrokerAdapter.

These tests use hand-crafted cassettes since real Schwab API access isn't
available yet (dev app pending approval). The cassettes will be replaced
with VCR recordings once live creds are available.

The tests verify:
1. The adapter correctly calls schwab-py methods
2. Responses are parsed into domain types
3. Error handling (auth failures, rate limits, not found)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from trading.adapters.schwab import (
    SchwabAccountNotFoundError,
    SchwabAuthError,
    SchwabBrokerAdapter,
    SchwabRateLimitError,
    SchwabSymbolNotFoundError,
)
from trading.adapters.schwab.oauth_store import FileTokenStore, OAuthTokens
from trading.domain import Symbol

CASSETTES_DIR = Path(__file__).parent / "cassettes" / "schwab"


def load_cassette(name: str) -> dict[str, Any]:
    """Load a cassette JSON file."""
    path = CASSETTES_DIR / f"{name}.json"
    return json.loads(path.read_text())


def make_mock_response(status_code: int, body: Any, headers: dict | None = None) -> MagicMock:
    """Create a mock httpx Response."""
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = body
    response.text = json.dumps(body) if isinstance(body, (dict, list)) else str(body)
    response.headers = headers or {}
    return response


@pytest.fixture
def mock_tokens() -> OAuthTokens:
    """Valid tokens that won't expire during tests."""
    return OAuthTokens(
        access_token="mock-access-token",
        refresh_token="mock-refresh-token",
        access_expires_at=datetime.now(UTC) + timedelta(minutes=25),
        refresh_expires_at=datetime.now(UTC) + timedelta(days=6),
    )


@pytest.fixture
def mock_token_store(mock_tokens: OAuthTokens, tmp_path: Path) -> FileTokenStore:
    """Token store with valid tokens."""
    store = FileTokenStore(path=tmp_path / "schwab_token.json")
    store.save(mock_tokens)
    return store


class TestSchwabBrokerAdapterAuth:
    """Auth flow and token handling tests."""

    def test_raises_auth_error_when_no_tokens(self, tmp_path: Path) -> None:
        """Adapter should raise SchwabAuthError if no tokens exist."""
        empty_store = FileTokenStore(path=tmp_path / "nonexistent.json")
        adapter = SchwabBrokerAdapter(
            client_id="test",
            client_secret="test",
            redirect_uri="https://localhost/callback",
            token_store=empty_store,
        )

        with pytest.raises(SchwabAuthError, match="No OAuth tokens found"):
            adapter._get_client()

        adapter.close()

    def test_raises_auth_error_when_refresh_expired(self, tmp_path: Path) -> None:
        """Adapter should raise SchwabAuthError if refresh token expired."""
        expired_tokens = OAuthTokens(
            access_token="expired-access",
            refresh_token="expired-refresh",
            access_expires_at=datetime.now(UTC) - timedelta(hours=1),
            refresh_expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        store = FileTokenStore(path=tmp_path / "expired.json")
        store.save(expired_tokens)

        adapter = SchwabBrokerAdapter(
            client_id="test",
            client_secret="test",
            redirect_uri="https://localhost/callback",
            token_store=store,
        )

        with pytest.raises(SchwabAuthError, match="Refresh token expired"):
            adapter._get_client()

        adapter.close()


class TestSchwabBrokerAdapterGetAccounts:
    """Tests for get_accounts method."""

    @pytest.mark.asyncio
    async def test_get_accounts_returns_broker_accounts(
        self, mock_token_store: FileTokenStore
    ) -> None:
        """get_accounts should return parsed BrokerAccount objects."""
        numbers_cassette = load_cassette("get_account_numbers")
        accounts_cassette = load_cassette("get_accounts")

        mock_client = MagicMock()
        mock_client.get_account_numbers.return_value = make_mock_response(
            200, numbers_cassette["interactions"][0]["response"]["body"]
        )
        mock_client.get_accounts.return_value = make_mock_response(
            200, accounts_cassette["interactions"][0]["response"]["body"]
        )

        with patch("schwab.auth.client_from_token_file", return_value=mock_client):
            adapter = SchwabBrokerAdapter(
                client_id="test",
                client_secret="test",
                redirect_uri="https://localhost/callback",
                token_store=mock_token_store,
            )

            accounts = await adapter.get_accounts()

            assert len(accounts) == 2
            # First account is margin
            margin_acct = next(a for a in accounts if "HASH123" in a.account_id)
            assert margin_acct.margin_enabled is True
            assert "****6789" in margin_acct.masked_schwab_id

            # Second account is IRA
            ira_acct = next(a for a in accounts if "HASH789" in a.account_id)
            assert ira_acct.margin_enabled is False

            adapter.close()


class TestSchwabBrokerAdapterGetAccount:
    """Tests for get_account method."""

    @pytest.mark.asyncio
    async def test_get_account_returns_full_snapshot(
        self, mock_token_store: FileTokenStore
    ) -> None:
        """get_account should return Account with balances and positions."""
        numbers_cassette = load_cassette("get_account_numbers")
        account_cassette = load_cassette("get_account_with_positions")

        mock_client = MagicMock()
        mock_client.get_account_numbers.return_value = make_mock_response(
            200, numbers_cassette["interactions"][0]["response"]["body"]
        )
        mock_client.get_account.return_value = make_mock_response(
            200, account_cassette["interactions"][0]["response"]["body"]
        )

        with patch("schwab.auth.client_from_token_file", return_value=mock_client):
            adapter = SchwabBrokerAdapter(
                client_id="test",
                client_secret="test",
                redirect_uri="https://localhost/callback",
                token_store=mock_token_store,
            )

            account = await adapter.get_account("HASH123ABC456DEF")

            assert account.account_id == "HASH123ABC456DEF"
            assert account.cash.amount > 0
            assert account.net_liquidation.amount > 0
            assert len(account.positions) == 3

            aapl = next(p for p in account.positions if p.symbol.ticker == "AAPL")
            assert aapl.quantity == 100
            assert aapl.market_value.amount > 0

            adapter.close()

    @pytest.mark.asyncio
    async def test_get_account_unknown_raises(self, mock_token_store: FileTokenStore) -> None:
        """get_account for unknown account should raise SchwabAccountNotFoundError."""
        numbers_cassette = load_cassette("get_account_numbers")

        mock_client = MagicMock()
        mock_client.get_account_numbers.return_value = make_mock_response(
            200, numbers_cassette["interactions"][0]["response"]["body"]
        )

        with patch("schwab.auth.client_from_token_file", return_value=mock_client):
            adapter = SchwabBrokerAdapter(
                client_id="test",
                client_secret="test",
                redirect_uri="https://localhost/callback",
                token_store=mock_token_store,
            )

            with pytest.raises(SchwabAccountNotFoundError, match="Unknown account"):
                await adapter.get_account("NONEXISTENT_HASH")

            adapter.close()


class TestSchwabBrokerAdapterGetQuote:
    """Tests for get_quote method."""

    @pytest.mark.asyncio
    async def test_get_quote_returns_quote(self, mock_token_store: FileTokenStore) -> None:
        """get_quote should return parsed Quote object."""
        quote_cassette = load_cassette("get_quote_aapl")

        mock_client = MagicMock()
        mock_client.get_quote.return_value = make_mock_response(
            200, quote_cassette["interactions"][0]["response"]["body"]
        )

        with patch("schwab.auth.client_from_token_file", return_value=mock_client):
            adapter = SchwabBrokerAdapter(
                client_id="test",
                client_secret="test",
                redirect_uri="https://localhost/callback",
                token_store=mock_token_store,
            )

            quote = await adapter.get_quote(Symbol("AAPL"))

            assert quote.symbol.ticker == "AAPL"
            assert quote.bid > 0
            assert quote.ask >= quote.bid
            assert quote.last > 0
            assert quote.volume > 0

            adapter.close()

    @pytest.mark.asyncio
    async def test_get_quote_not_found_raises(self, mock_token_store: FileTokenStore) -> None:
        """get_quote for unknown symbol should raise SchwabSymbolNotFoundError."""
        mock_client = MagicMock()
        mock_client.get_quote.return_value = make_mock_response(404, {"error": "Not found"})

        with patch("schwab.auth.client_from_token_file", return_value=mock_client):
            adapter = SchwabBrokerAdapter(
                client_id="test",
                client_secret="test",
                redirect_uri="https://localhost/callback",
                token_store=mock_token_store,
            )

            with pytest.raises(SchwabSymbolNotFoundError, match="UNKNWN"):
                await adapter.get_quote(Symbol("UNKNWN"))

            adapter.close()


class TestSchwabBrokerAdapterGetOrders:
    """Tests for get_orders method."""

    @pytest.mark.asyncio
    async def test_get_orders_returns_raw_dicts(self, mock_token_store: FileTokenStore) -> None:
        """get_orders should return tuple of raw dicts (not modeled in v1)."""
        numbers_cassette = load_cassette("get_account_numbers")
        orders_cassette = load_cassette("get_orders")

        mock_client = MagicMock()
        mock_client.get_account_numbers.return_value = make_mock_response(
            200, numbers_cassette["interactions"][0]["response"]["body"]
        )
        mock_client.get_orders_for_account.return_value = make_mock_response(
            200, orders_cassette["interactions"][0]["response"]["body"]
        )

        with patch("schwab.auth.client_from_token_file", return_value=mock_client):
            adapter = SchwabBrokerAdapter(
                client_id="test",
                client_secret="test",
                redirect_uri="https://localhost/callback",
                token_store=mock_token_store,
            )

            orders = await adapter.get_orders("HASH123ABC456DEF")

            assert len(orders) == 2
            assert all(isinstance(o, dict) for o in orders)
            assert orders[0]["orderId"] == 12345
            assert orders[0]["status"] == "FILLED"

            adapter.close()


class TestSchwabBrokerAdapterGetTransactions:
    """Tests for get_transactions method."""

    @pytest.mark.asyncio
    async def test_get_transactions_returns_raw_dicts(
        self, mock_token_store: FileTokenStore
    ) -> None:
        """get_transactions should return tuple of raw dicts."""
        numbers_cassette = load_cassette("get_account_numbers")
        txns_cassette = load_cassette("get_transactions")

        mock_client = MagicMock()
        mock_client.get_account_numbers.return_value = make_mock_response(
            200, numbers_cassette["interactions"][0]["response"]["body"]
        )
        mock_client.get_transactions.return_value = make_mock_response(
            200, txns_cassette["interactions"][0]["response"]["body"]
        )

        with patch("schwab.auth.client_from_token_file", return_value=mock_client):
            adapter = SchwabBrokerAdapter(
                client_id="test",
                client_secret="test",
                redirect_uri="https://localhost/callback",
                token_store=mock_token_store,
            )

            txns = await adapter.get_transactions("HASH123ABC456DEF")

            assert len(txns) == 3
            assert all(isinstance(t, dict) for t in txns)
            assert txns[0]["type"] == "TRADE"
            assert txns[1]["type"] == "DIVIDEND_OR_INTEREST"
            assert txns[2]["type"] == "ACH_RECEIPT"

            adapter.close()


class TestSchwabBrokerAdapterErrorHandling:
    """Error handling and edge case tests."""

    @pytest.mark.asyncio
    async def test_rate_limit_raises_with_retry_after(
        self, mock_token_store: FileTokenStore
    ) -> None:
        """Rate limit response should raise SchwabRateLimitError with retry_after."""
        mock_client = MagicMock()
        mock_client.get_quote.return_value = make_mock_response(
            429, {"error": "Rate limit"}, headers={"Retry-After": "60"}
        )

        with patch("schwab.auth.client_from_token_file", return_value=mock_client):
            adapter = SchwabBrokerAdapter(
                client_id="test",
                client_secret="test",
                redirect_uri="https://localhost/callback",
                token_store=mock_token_store,
            )

            with pytest.raises(SchwabRateLimitError) as exc_info:
                await adapter.get_quote(Symbol("AAPL"))

            assert exc_info.value.retry_after == 60

            adapter.close()

    @pytest.mark.asyncio
    async def test_auth_failure_raises_schwab_auth_error(
        self, mock_token_store: FileTokenStore
    ) -> None:
        """401/403 response should raise SchwabAuthError."""
        mock_client = MagicMock()
        mock_client.get_quote.return_value = make_mock_response(401, {"error": "Unauthorized"})

        with patch("schwab.auth.client_from_token_file", return_value=mock_client):
            adapter = SchwabBrokerAdapter(
                client_id="test",
                client_secret="test",
                redirect_uri="https://localhost/callback",
                token_store=mock_token_store,
            )

            with pytest.raises(SchwabAuthError, match="Authentication failed"):
                await adapter.get_quote(Symbol("AAPL"))

            adapter.close()


class TestStreamQuotes:
    """Tests for stream_quotes stub implementation."""

    @pytest.mark.asyncio
    async def test_stream_quotes_yields_single_snapshot(
        self, mock_token_store: FileTokenStore
    ) -> None:
        """stream_quotes stub yields one quote per symbol."""
        quote_cassette = load_cassette("get_quote_aapl")

        mock_client = MagicMock()
        mock_client.get_quote.return_value = make_mock_response(
            200, quote_cassette["interactions"][0]["response"]["body"]
        )

        with patch("schwab.auth.client_from_token_file", return_value=mock_client):
            adapter = SchwabBrokerAdapter(
                client_id="test",
                client_secret="test",
                redirect_uri="https://localhost/callback",
                token_store=mock_token_store,
            )

            quotes = []
            async for q in adapter.stream_quotes((Symbol("AAPL"),)):
                quotes.append(q)

            assert len(quotes) == 1
            assert quotes[0].symbol.ticker == "AAPL"

            adapter.close()
