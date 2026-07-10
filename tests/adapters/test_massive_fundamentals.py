"""Massive fundamentals parsing + merge — pure, no network."""

from __future__ import annotations

from datetime import date

import pytest

from trading.adapters.massive.fundamentals import (
    BalanceSheet,
    CashFlowStatement,
    IncomeStatement,
    build_price_lookup,
    merge_fundamentals,
    parse_balance_sheets,
    parse_cash_flow_statements,
    parse_income_statements,
)

_INCOME_PAYLOAD = {
    "status": "OK",
    "results": [
        {
            "cik": "0000320193",
            "tickers": ["AAPL"],
            "period_end": "2025-12-27",
            "filing_date": "2026-01-30",
            "fiscal_year": 2026,
            "fiscal_quarter": 1,
            "timeframe": "trailing_twelve_months",
            "revenue": 400_000_000_000,
            "gross_profit": 180_000_000_000,
            "operating_income": 120_000_000_000,
            "net_income_loss_attributable_common_shareholders": 100_000_000_000,
            "basic_earnings_per_share": 6.7,
            "diluted_earnings_per_share": 6.5,
            "diluted_shares_outstanding": 15_000_000_000,
        },
    ],
}

_BALANCE_PAYLOAD = {
    "status": "OK",
    "results": [
        {
            "period_end": "2025-12-27",
            "filing_date": "2026-01-30",
            "timeframe": "quarterly",
            "total_assets": 360_000_000_000,
            "total_current_assets": 140_000_000_000,
            "total_current_liabilities": 130_000_000_000,
            "total_equity_attributable_to_parent": 80_000_000_000,
            "debt_current": 12_000_000_000,
            "long_term_debt_and_capital_lease_obligations": 85_000_000_000,
        },
    ],
}

_CASHFLOW_PAYLOAD = {
    "status": "OK",
    "results": [
        {
            "period_end": "2025-12-27",
            "filing_date": "2026-01-30",
            "timeframe": "trailing_twelve_months",
            "net_cash_from_operating_activities": 115_000_000_000,
            "purchase_of_property_plant_and_equipment": 11_000_000_000,
        },
    ],
}


class TestParsing:
    def test_parse_income_statements(self) -> None:
        rows = parse_income_statements(_INCOME_PAYLOAD)
        assert len(rows) == 1
        row = rows[0]
        assert row.period_end == date(2025, 12, 27)
        assert row.filing_date == date(2026, 1, 30)
        assert row.revenue == 400_000_000_000
        assert row.net_income == 100_000_000_000
        assert row.diluted_eps == 6.5

    def test_parse_balance_sheets(self) -> None:
        rows = parse_balance_sheets(_BALANCE_PAYLOAD)
        assert rows[0].total_equity == 80_000_000_000
        assert rows[0].debt_current == 12_000_000_000
        assert rows[0].long_term_debt == 85_000_000_000

    def test_parse_cash_flow_statements(self) -> None:
        rows = parse_cash_flow_statements(_CASHFLOW_PAYLOAD)
        assert rows[0].operating_cash_flow == 115_000_000_000
        assert rows[0].capital_expenditures == 11_000_000_000

    def test_parse_empty_results(self) -> None:
        assert parse_income_statements({"status": "OK", "results": []}) == []
        assert parse_income_statements({"status": "OK"}) == []

    def test_parse_rejects_malformed_rows(self) -> None:
        with pytest.raises(TypeError):
            parse_income_statements({"results": ["not-an-object"]})
        with pytest.raises(TypeError):
            parse_income_statements({"results": [{"period_end": None}]})


def _income(period_end: date, filed: date, revenue: float, **overrides: object) -> IncomeStatement:
    defaults: dict = {
        "period_end": period_end,
        "filing_date": filed,
        "revenue": revenue,
        "gross_profit": revenue * 0.45,
        "operating_income": revenue * 0.30,
        "net_income": revenue * 0.25,
        "diluted_eps": 6.5,
        "diluted_shares": 15_000_000_000,
    }
    defaults.update(overrides)
    return IncomeStatement(**defaults)


class TestMerge:
    def test_ratios_computed_per_period(self) -> None:
        pe = date(2025, 12, 27)
        filed = date(2026, 1, 30)
        incomes = [_income(pe, filed, 400e9)]
        balances = [
            BalanceSheet(
                period_end=pe,
                filing_date=filed,
                total_equity=80e9,
                total_current_assets=140e9,
                total_current_liabilities=130e9,
                debt_current=12e9,
                long_term_debt=85e9,
            )
        ]
        cashflows = [
            CashFlowStatement(
                period_end=pe,
                filing_date=filed,
                operating_cash_flow=115e9,
                capital_expenditures=11e9,
            )
        ]
        prices = {filed: 200.0}

        [row] = merge_fundamentals(incomes, balances, cashflows, prices)
        assert row.report_period == "2025-12-27"
        assert row.filing_date == "2026-01-30"
        assert row.gross_margin == pytest.approx(0.45)
        assert row.operating_margin == pytest.approx(0.30)
        assert row.net_margin == pytest.approx(0.25)
        assert row.return_on_equity == pytest.approx(100e9 / 80e9)
        assert row.debt_to_equity == pytest.approx(97e9 / 80e9)
        assert row.current_ratio == pytest.approx(140e9 / 130e9)
        assert row.earnings_per_share == 6.5
        assert row.book_value_per_share == pytest.approx(80e9 / 15e9)
        # FCF = 115e9 op cash flow - 11e9 capex
        assert row.free_cash_flow_per_share == pytest.approx(104e9 / 15e9)
        assert row.market_cap == pytest.approx(200.0 * 15e9)
        assert row.price_to_earnings_ratio == pytest.approx(200.0 / 6.5)

    def test_revenue_growth_is_yoy_of_ttm(self) -> None:
        # 6 TTM rows one quarter apart; yoy compares to 4 rows earlier.
        rows = [
            _income(date(2025, 12, 27), date(2026, 1, 30), 440e9),
            _income(date(2025, 9, 27), date(2025, 10, 30), 430e9),
            _income(date(2025, 6, 27), date(2025, 7, 30), 420e9),
            _income(date(2025, 3, 27), date(2025, 4, 30), 410e9),
            _income(date(2024, 12, 27), date(2025, 1, 30), 400e9),
            _income(date(2024, 9, 27), date(2024, 10, 30), 390e9),
        ]
        merged = merge_fundamentals(rows, [], [], {})
        assert merged[0].revenue_growth == pytest.approx((440e9 - 400e9) / 400e9)
        assert merged[1].revenue_growth == pytest.approx((430e9 - 390e9) / 390e9)
        # No row 4 quarters earlier → None
        assert merged[2].revenue_growth is None

    def test_missing_balance_and_prices_fail_soft(self) -> None:
        [row] = merge_fundamentals(
            [_income(date(2025, 12, 27), date(2026, 1, 30), 400e9)], [], [], None
        )
        assert row.return_on_equity is None
        assert row.debt_to_equity is None
        assert row.market_cap is None
        assert row.price_to_earnings_ratio is None
        # Income-only metrics still present
        assert row.net_margin == pytest.approx(0.25)

    def test_newest_first_regardless_of_input_order(self) -> None:
        merged = merge_fundamentals(
            [
                _income(date(2024, 12, 27), date(2025, 1, 30), 400e9),
                _income(date(2025, 12, 27), date(2026, 1, 30), 440e9),
            ],
            [],
            [],
            {},
        )
        assert [r.report_period for r in merged] == ["2025-12-27", "2024-12-27"]


class TestPriceLookup:
    def test_filing_on_non_trading_day_walks_back(self) -> None:
        closes = {
            date(2026, 1, 29): 199.0,  # Thursday
            date(2026, 1, 30): 200.0,  # Friday
        }
        lookup = build_price_lookup(
            [date(2026, 1, 30), date(2026, 2, 1)],  # Friday + Sunday
            closes,
        )
        assert lookup[date(2026, 1, 30)] == 200.0
        assert lookup[date(2026, 2, 1)] == 200.0  # walked back to Friday

    def test_filing_before_all_prices_is_absent(self) -> None:
        lookup = build_price_lookup([date(2020, 1, 1)], {date(2026, 1, 30): 200.0})
        assert date(2020, 1, 1) not in lookup
