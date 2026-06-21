from __future__ import annotations

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from trading.adapters.quiver.exceptions import QuiverParseError
from trading.adapters.quiver.parsing import (
    parse_dollar_range,
    parse_quiver_date,
    parse_symbol,
    parse_trade_disclosure,
    parse_trade_disclosures,
    parse_transaction_type,
)
from trading.domain import Symbol, TransactionType


def _record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "Representative": "Jane Doe",
        "BioGuideID": "D000001",
        "ReportDate": "2026-06-09T00:00:00Z",
        "TransactionDate": "2026-05-02",
        "Ticker": "NVDA",
        "Transaction": "Purchase",
        "Range": "$1,001 - $15,000",
        "Description": "NVIDIA Corp",
        "Party": "D",
    }
    record.update(overrides)
    return record


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$1,001 - $15,000", (1001, 15000)),
        ("$50,001 - $100,000", (50001, 100000)),
        ("$1,000,001 - $5,000,000", (1000001, 5000000)),
        ("Over $50,000,000", (50000000, None)),
        (">$50,000,000", (50000000, None)),
        ("$5,000,000+", (5000000, None)),
        ("1001", (1001, None)),
        ("", (None, None)),
        ("Undisclosed", (None, None)),
        (None, (None, None)),
    ],
)
def test_parse_dollar_range_documented_formats(
    raw: str | None,
    expected: tuple[int | None, int | None],
) -> None:
    assert parse_dollar_range(raw) == expected


@given(
    low=st.integers(min_value=1, max_value=50_000_000),
    extra=st.integers(min_value=0, max_value=50_000_000),
)
def test_parse_dollar_range_round_trip(low: int, extra: int) -> None:
    high = low + extra
    raw = f"${low:,} - ${high:,}"
    assert parse_dollar_range(raw) == (low, high)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Purchase", TransactionType.PURCHASE),
        ("Sale", TransactionType.SALE),
        ("Sale (Partial)", TransactionType.SALE_PARTIAL),
        ("Exchange", TransactionType.EXCHANGE),
        ("Other", TransactionType.OTHER),
        ("Gift", TransactionType.OTHER),
        (None, TransactionType.OTHER),
    ],
)
def test_transaction_type_mapping(raw: str | None, expected: TransactionType) -> None:
    assert parse_transaction_type(raw) is expected


@pytest.mark.parametrize("raw", [None, "", "-", "N/A", "not a ticker"])
def test_missing_or_invalid_ticker_becomes_none(raw: str | None) -> None:
    assert parse_symbol(raw) is None


def test_symbol_is_normalized() -> None:
    assert parse_symbol("brk/b") == Symbol("BRK.B")


@pytest.mark.parametrize(
    "raw",
    [
        "2026-06-09",
        "2026-06-09T00:00:00Z",
        "2026-06-09 00:00:00",
        "20260609",
    ],
)
def test_date_parsing(raw: str) -> None:
    assert parse_quiver_date(raw) == date(2026, 6, 9)


def test_parse_trade_disclosure_v1() -> None:
    disclosure = parse_trade_disclosure(_record())
    assert disclosure.member_id == "D000001"
    assert disclosure.member_name == "Jane Doe"
    assert disclosure.symbol == Symbol("NVDA")
    assert disclosure.asset_description == "NVIDIA Corp"
    assert disclosure.transaction_type is TransactionType.PURCHASE
    assert disclosure.transaction_date == date(2026, 5, 2)
    assert disclosure.disclosure_date == date(2026, 6, 9)
    assert disclosure.amount_range_low == 1001
    assert disclosure.amount_range_high == 15000


def test_parse_trade_disclosure_v2_missing_ticker() -> None:
    disclosure = parse_trade_disclosure(
        {
            "Name": "John Smith",
            "BioGuideID": "S000001",
            "Filed": "2026-06-10T00:00:00Z",
            "Traded": "2026-05-03T00:00:00Z",
            "Ticker": "-",
            "Transaction": "Sale (Partial)",
            "Trade_Size_USD": "$50,001",
            "Company": "Municipal bond fund",
            "Party": "R",
            "Chamber": "Senate",
        }
    )
    assert disclosure.symbol is None
    assert disclosure.asset_description == "Municipal bond fund"
    assert disclosure.transaction_type is TransactionType.SALE_PARTIAL
    assert disclosure.amount_range_low == 50001
    assert disclosure.amount_range_high is None


def test_malformed_records_are_skipped_not_raised() -> None:
    records = [
        _record(Ticker="AAPL"),
        _record(TransactionDate=None),
        _record(Representative=None),
    ]
    parsed = parse_trade_disclosures(records)
    assert len(parsed) == 1
    assert parsed[0].symbol == Symbol("AAPL")


def test_malformed_single_record_raises_parse_error() -> None:
    with pytest.raises(QuiverParseError):
        parse_trade_disclosure(_record(TransactionDate=None))
