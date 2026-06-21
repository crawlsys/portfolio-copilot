"""Unit tests for shared domain value objects. No I/O, fast."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from trading.domain import AssetClass, DateRange, Money, Symbol

# --- Money -------------------------------------------------------------------


class TestMoneyConstruction:
    def test_usd_from_string_normalizes(self) -> None:
        m = Money.usd("100.50")
        assert m.amount == Decimal("100.50")
        assert m.currency == "USD"

    def test_usd_from_decimal(self) -> None:
        m = Money.usd(Decimal("99.9999"))  # exactly 4 dp — OK
        assert m.amount == Decimal("99.9999")

    def test_usd_from_int(self) -> None:
        m = Money.usd(42)
        assert m.amount == 42

    def test_rejects_float(self) -> None:
        with pytest.raises(TypeError, match="must be Decimal"):
            Money(amount=1.5)  # type: ignore[arg-type]

    def test_rejects_more_than_4_dp(self) -> None:
        with pytest.raises(ValueError, match="precision"):
            Money.usd("1.00001")

    def test_rejects_bad_currency(self) -> None:
        with pytest.raises(ValueError, match="3-letter ISO"):
            Money(amount=Decimal("1"), currency="DOLLAR")

    def test_zero_factory(self) -> None:
        z = Money.zero()
        assert z.amount == 0
        assert z.is_zero()
        assert not z.is_negative()


class TestMoneyArithmetic:
    def test_add_same_currency(self) -> None:
        assert (Money.usd("1.50") + Money.usd("2.50")).amount == Decimal("4.00")

    def test_sub_same_currency(self) -> None:
        assert (Money.usd("5.00") - Money.usd("2.00")).amount == Decimal("3.00")

    def test_add_mismatched_currency_raises(self) -> None:
        with pytest.raises(ValueError, match="Currency mismatch"):
            Money.usd("1") + Money(amount=Decimal("1"), currency="EUR")

    def test_mul_by_int(self) -> None:
        assert (Money.usd("10") * 3).amount == 30

    def test_mul_by_decimal(self) -> None:
        assert (Money.usd("10") * Decimal("1.5")).amount == Decimal("15.0")

    def test_rmul(self) -> None:
        assert (3 * Money.usd("10")).amount == 30

    def test_negative_result(self) -> None:
        diff = Money.usd("3") - Money.usd("5")
        assert diff.is_negative()


@given(
    a=st.decimals(min_value=Decimal("-1e9"), max_value=Decimal("1e9"), places=2),
    b=st.decimals(min_value=Decimal("-1e9"), max_value=Decimal("1e9"), places=2),
)
def test_money_add_sub_round_trip(a: Decimal, b: Decimal) -> None:
    """(a + b) - b == a, for any two valid decimals."""
    ma, mb = Money.usd(a), Money.usd(b)
    assert ((ma + mb) - mb).amount == a


# --- Symbol ------------------------------------------------------------------


class TestSymbol:
    def test_equity_valid(self) -> None:
        assert str(Symbol("AAPL")) == "AAPL"

    def test_equity_with_dot(self) -> None:
        Symbol("BRK.B")  # no raise

    def test_equity_lowercase_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid equity"):
            Symbol("aapl")

    def test_equity_too_long(self) -> None:
        with pytest.raises(ValueError, match="Invalid equity"):
            Symbol("ABCDEFG")

    def test_equity_empty_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            Symbol("")

    def test_option_valid(self) -> None:
        Symbol("NVDA240315C00080000", asset_class=AssetClass.OPTION)

    def test_option_bad_format_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid OCC"):
            Symbol("NVDA-2024", asset_class=AssetClass.OPTION)

    def test_option_treated_as_equity_rejected(self) -> None:
        """An OCC-shaped string passed as equity should be rejected by the equity rule."""
        with pytest.raises(ValueError, match="Invalid equity"):
            Symbol("NVDA240315C00080000")  # default asset_class=EQUITY


# --- DateRange ---------------------------------------------------------------


class TestDateRange:
    def test_valid(self) -> None:
        DateRange(start=date(2026, 1, 1), end=date(2026, 1, 31))

    def test_end_before_start_raises(self) -> None:
        with pytest.raises(ValueError, match="end < start"):
            DateRange(start=date(2026, 2, 1), end=date(2026, 1, 1))

    def test_same_day_ok(self) -> None:
        DateRange(start=date(2026, 1, 1), end=date(2026, 1, 1))
