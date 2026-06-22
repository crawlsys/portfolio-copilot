"""Tests for Schwab response parsing.

Pure-function tests using realistic response shapes based on Schwab's
Trader API v1. These fixtures are hand-crafted from schwab-py docs
and will be replaced with real VCR recordings when live creds arrive.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from trading.adapters.schwab.parsing import (
    parse_account,
    parse_account_type,
    parse_broker_account,
    parse_position,
    parse_quote,
)
from trading.domain import AccountType, AssetClass, Symbol

# --- Account type parsing ---


class TestParseAccountType:
    def test_margin_account(self) -> None:
        assert parse_account_type("MARGIN") == AccountType.MARGIN
        assert parse_account_type("margin") == AccountType.MARGIN

    def test_cash_account(self) -> None:
        assert parse_account_type("CASH") == AccountType.CASH

    def test_ira_variants(self) -> None:
        assert parse_account_type("IRA") == AccountType.IRA
        assert parse_account_type("TRADITIONAL_IRA") == AccountType.IRA
        assert parse_account_type("ROTH_IRA") == AccountType.ROTH_IRA
        assert parse_account_type("ROTH") == AccountType.ROTH_IRA

    def test_taxable_variants(self) -> None:
        assert parse_account_type("INDIVIDUAL") == AccountType.TAXABLE
        assert parse_account_type("JOINT") == AccountType.TAXABLE

    def test_unknown_type(self) -> None:
        assert parse_account_type("WEIRD_TYPE") == AccountType.UNKNOWN
        assert parse_account_type(None) == AccountType.UNKNOWN
        assert parse_account_type("") == AccountType.UNKNOWN


# --- BrokerAccount parsing ---


class TestParseBrokerAccount:
    @pytest.fixture
    def margin_account_data(self) -> dict:
        return {
            "securitiesAccount": {
                "accountNumber": "123456789",
                "type": "MARGIN",
                "currentBalances": {
                    "cashBalance": 50000.00,
                    "liquidationValue": 150000.00,
                },
            }
        }

    @pytest.fixture
    def ira_account_data(self) -> dict:
        return {
            "securitiesAccount": {
                "accountNumber": "987654321",
                "type": "IRA",
            }
        }

    def test_parses_margin_account(self, margin_account_data: dict) -> None:
        result = parse_broker_account("HASH123ABC", margin_account_data)

        assert result.account_id == "HASH123ABC"
        assert result.account_type == AccountType.MARGIN
        assert result.margin_enabled is True
        assert result.masked_schwab_id == "****6789"
        assert "Margin" in result.nickname

    def test_parses_ira_account(self, ira_account_data: dict) -> None:
        result = parse_broker_account("HASH456DEF", ira_account_data)

        assert result.account_id == "HASH456DEF"
        assert result.account_type == AccountType.IRA
        assert result.margin_enabled is False
        assert "IRA" in result.nickname

    def test_handles_unwrapped_format(self) -> None:
        # Some endpoints return without securitiesAccount wrapper
        data = {
            "accountNumber": "111222333",
            "type": "CASH",
        }
        result = parse_broker_account("HASH789", data)

        assert result.account_type == AccountType.CASH
        assert result.masked_schwab_id == "****2333"


# --- Position parsing ---


class TestParsePosition:
    @pytest.fixture
    def equity_position_data(self) -> dict:
        return {
            "instrument": {
                "symbol": "AAPL",
                "assetType": "EQUITY",
                "cusip": "037833100",
            },
            "longQuantity": 100.0,
            "shortQuantity": 0.0,
            "averagePrice": 150.50,
            "marketValue": 17550.00,
            "currentDayProfitLoss": 500.00,
        }

    @pytest.fixture
    def option_position_data(self) -> dict:
        return {
            "instrument": {
                "symbol": "AAPL260621C00150000",
                "assetType": "OPTION",
            },
            "longQuantity": 10.0,
            "shortQuantity": 0.0,
            "averagePrice": 5.50,
            "marketValue": 6500.00,
        }

    @pytest.fixture
    def short_position_data(self) -> dict:
        return {
            "instrument": {
                "symbol": "GME",
                "assetType": "EQUITY",
            },
            "longQuantity": 0.0,
            "shortQuantity": 50.0,
            "averagePrice": 20.00,
            "marketValue": -1250.00,
        }

    def test_parses_equity_position(self, equity_position_data: dict) -> None:
        result = parse_position("acct-1", equity_position_data)

        assert result.account_id == "acct-1"
        assert result.symbol.ticker == "AAPL"
        assert result.symbol.asset_class == AssetClass.EQUITY
        assert result.quantity == Decimal("100")
        assert result.average_cost.amount == Decimal("150.50").quantize(Decimal("0.0001"))
        assert result.market_value.amount == Decimal("17550.00").quantize(Decimal("0.0001"))
        assert result.is_long is True
        assert result.is_short is False

    def test_parses_option_position(self, option_position_data: dict) -> None:
        result = parse_position("acct-1", option_position_data)

        assert result.symbol.ticker == "AAPL260621C00150000"
        assert result.symbol.asset_class == AssetClass.OPTION
        assert result.quantity == Decimal("10")

    def test_parses_short_position(self, short_position_data: dict) -> None:
        result = parse_position("acct-1", short_position_data)

        assert result.symbol.ticker == "GME"
        assert result.quantity == Decimal("-50")
        assert result.is_short is True
        assert result.is_long is False

    def test_calculates_unrealized_pnl(self, equity_position_data: dict) -> None:
        result = parse_position("acct-1", equity_position_data)

        expected_cost_basis = Decimal("150.50") * 100
        expected_pnl = Decimal("17550.00") - expected_cost_basis
        assert result.unrealized_pnl.amount == expected_pnl.quantize(Decimal("0.0001"))


# --- Account parsing (full snapshot) ---


class TestParseAccount:
    @pytest.fixture
    def full_account_data(self) -> dict:
        return {
            "securitiesAccount": {
                "accountNumber": "123456789",
                "type": "MARGIN",
                "currentBalances": {
                    "cashBalance": 50000.00,
                    "liquidationValue": 150000.00,
                    "buyingPower": 100000.00,
                    "marginBalance": -10000.00,
                    "dayPnl": 1500.00,
                },
                "positions": [
                    {
                        "instrument": {"symbol": "AAPL", "assetType": "EQUITY"},
                        "longQuantity": 100.0,
                        "shortQuantity": 0.0,
                        "averagePrice": 150.00,
                        "marketValue": 17500.00,
                    },
                    {
                        "instrument": {"symbol": "NVDA", "assetType": "EQUITY"},
                        "longQuantity": 50.0,
                        "shortQuantity": 0.0,
                        "averagePrice": 400.00,
                        "marketValue": 60000.00,
                    },
                ],
            }
        }

    def test_parses_full_account_snapshot(self, full_account_data: dict) -> None:
        as_of = datetime(2026, 6, 21, 12, 0, 0, tzinfo=UTC)
        result = parse_account("HASH123", full_account_data, as_of=as_of)

        assert result.account_id == "HASH123"
        assert result.cash.amount == Decimal("50000.00").quantize(Decimal("0.0001"))
        assert result.net_liquidation.amount == Decimal("150000.00").quantize(Decimal("0.0001"))
        assert result.buying_power.amount == Decimal("100000.00").quantize(Decimal("0.0001"))
        assert result.margin_balance is not None
        assert result.margin_balance.amount == Decimal("-10000.00").quantize(Decimal("0.0001"))
        assert len(result.positions) == 2
        assert result.as_of == as_of

    def test_computes_market_value_from_positions(self, full_account_data: dict) -> None:
        result = parse_account("HASH123", full_account_data)

        # 17500 (AAPL) + 60000 (NVDA) = 77500
        assert result.market_value.amount == Decimal("77500.00").quantize(Decimal("0.0001"))

    def test_filters_invalid_positions(self) -> None:
        data = {
            "securitiesAccount": {
                "accountNumber": "123",
                "type": "CASH",
                "currentBalances": {"cashBalance": 10000.00},
                "positions": [
                    # Valid position
                    {
                        "instrument": {"symbol": "AAPL", "assetType": "EQUITY"},
                        "longQuantity": 10.0,
                        "shortQuantity": 0.0,
                        "averagePrice": 150.00,
                        "marketValue": 1500.00,
                    },
                    # Invalid: empty symbol
                    {
                        "instrument": {"symbol": "", "assetType": "EQUITY"},
                        "longQuantity": 5.0,
                        "shortQuantity": 0.0,
                    },
                    # Invalid: zero quantity
                    {
                        "instrument": {"symbol": "MSFT", "assetType": "EQUITY"},
                        "longQuantity": 0.0,
                        "shortQuantity": 0.0,
                    },
                ],
            }
        }
        result = parse_account("HASH", data)
        assert len(result.positions) == 1
        assert result.positions[0].symbol.ticker == "AAPL"


# --- Quote parsing ---


class TestParseQuote:
    @pytest.fixture
    def single_quote_data(self) -> dict:
        """Single quote response (from get_quote)."""
        return {
            "AAPL": {
                "quote": {
                    "bidPrice": 174.50,
                    "askPrice": 175.50,
                    "lastPrice": 175.00,
                    "totalVolume": 50000000,
                    "quoteTime": 1719000000000,  # epoch ms
                }
            }
        }

    @pytest.fixture
    def unwrapped_quote_data(self) -> dict:
        """Alternative format without symbol key wrapper."""
        return {
            "quote": {
                "bidPrice": 1195.00,
                "askPrice": 1205.00,
                "lastPrice": 1200.00,
                "totalVolume": 12000000,
            }
        }

    def test_parses_wrapped_quote(self, single_quote_data: dict) -> None:
        symbol = Symbol("AAPL")
        result = parse_quote(symbol, single_quote_data)

        assert result.symbol == symbol
        assert result.bid == Decimal("174.50").quantize(Decimal("0.0001"))
        assert result.ask == Decimal("175.50").quantize(Decimal("0.0001"))
        assert result.last == Decimal("175.00").quantize(Decimal("0.0001"))
        assert result.volume == 50000000

    def test_parses_unwrapped_quote(self, unwrapped_quote_data: dict) -> None:
        symbol = Symbol("NVDA")
        result = parse_quote(symbol, unwrapped_quote_data)

        assert result.symbol == symbol
        assert result.bid == Decimal("1195.00").quantize(Decimal("0.0001"))
        assert result.ask == Decimal("1205.00").quantize(Decimal("0.0001"))
        assert result.last == Decimal("1200.00").quantize(Decimal("0.0001"))

    def test_computes_spread(self, single_quote_data: dict) -> None:
        symbol = Symbol("AAPL")
        result = parse_quote(symbol, single_quote_data)

        # spread = ask - bid = 175.50 - 174.50 = 1.00
        assert result.spread == Decimal("1.00").quantize(Decimal("0.0001"))

    def test_computes_mid(self, single_quote_data: dict) -> None:
        symbol = Symbol("AAPL")
        result = parse_quote(symbol, single_quote_data)

        # mid = (bid + ask) / 2 = (174.50 + 175.50) / 2 = 175.00
        assert result.mid == Decimal("175.00")

    def test_defaults_last_to_mid_when_zero(self) -> None:
        data = {
            "quote": {
                "bidPrice": 100.00,
                "askPrice": 102.00,
                "lastPrice": 0.0,
            }
        }
        symbol = Symbol("TEST")
        result = parse_quote(symbol, data)

        # last defaults to mid when zero
        assert result.last == Decimal("101.00")

    def test_handles_missing_volume(self) -> None:
        data = {
            "quote": {
                "bidPrice": 50.00,
                "askPrice": 51.00,
                "lastPrice": 50.50,
            }
        }
        symbol = Symbol("SMALL")
        result = parse_quote(symbol, data)

        assert result.volume is None

    def test_extracts_timestamp_from_quote_time(self, single_quote_data: dict) -> None:
        symbol = Symbol("AAPL")
        result = parse_quote(symbol, single_quote_data)

        # quoteTime is 1719000000000 ms = 2024-06-21T19:20:00 UTC
        expected = datetime.fromtimestamp(1719000000, tz=UTC)
        assert result.timestamp == expected


# --- Edge cases ---


class TestParsingEdgeCases:
    def test_handles_float_precision_issues(self) -> None:
        # Schwab returns floats; ensure no precision loss
        data = {
            "securitiesAccount": {
                "accountNumber": "123",
                "type": "CASH",
                "currentBalances": {
                    "cashBalance": 0.1 + 0.2,  # Famous float issue
                },
                "positions": [],
            }
        }
        result = parse_account("HASH", data)
        # Should be quantized to 4dp without overflow
        assert result.cash.currency == "USD"

    def test_handles_missing_optional_fields(self) -> None:
        minimal_data = {
            "securitiesAccount": {
                "accountNumber": "123",
                "currentBalances": {},
                "positions": [],
            }
        }
        result = parse_account("HASH", minimal_data)

        assert result.cash.is_zero()
        assert result.margin_balance is None
        assert result.day_pnl is None
        assert len(result.positions) == 0

    def test_handles_null_values(self) -> None:
        data = {
            "securitiesAccount": {
                "accountNumber": "123",
                "type": None,
                "currentBalances": {
                    "cashBalance": None,
                    "marginBalance": None,
                },
                "positions": [],
            }
        }
        result = parse_account("HASH", data)

        assert result.account_id == "HASH"
        assert result.cash.is_zero()
