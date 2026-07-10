"""Massive fundamentals — pure parsers + the period merge.

Massive's fundamentals suite (Financials & Ratios Expansion entitlement)
returns raw statement lines per (period_end, timeframe) with a `filing_date`
stamp. Point-in-time discipline: every query filters `filing_date.lte` — never
`period_end`, which precedes public availability by 3-6 weeks and would leak
the future into an as-of view.

The ratios endpoint is a current-values screener (no history), so per-period
ratios are computed here from the three statements:
- income (trailing_twelve_months): margins, EPS, revenue growth (yoy of TTM)
- balance sheet (quarterly): ROE denominator, D/E, current ratio, BVPS
- cash flow (trailing_twelve_months): FCF/share (op cash flow - capex)
Market cap and P/E use the daily close ON the filing date (the price the
market actually offered when the numbers became public), supplied by the
caller as a date-indexed price series.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from trading.application.advisors.snapshot import PeriodFundamentals

JsonObject = dict[str, object]

# yoy of trailing-twelve-month rows: compare to the row 4 quarters earlier.
YOY_OFFSET = 4


@dataclass(frozen=True)
class IncomeStatement:
    period_end: date
    filing_date: date | None
    revenue: float | None
    gross_profit: float | None
    operating_income: float | None
    net_income: float | None
    diluted_eps: float | None
    diluted_shares: float | None


@dataclass(frozen=True)
class BalanceSheet:
    period_end: date
    filing_date: date | None
    total_equity: float | None
    total_current_assets: float | None
    total_current_liabilities: float | None
    debt_current: float | None
    long_term_debt: float | None


@dataclass(frozen=True)
class CashFlowStatement:
    period_end: date
    filing_date: date | None
    operating_cash_flow: float | None
    capital_expenditures: float | None


def parse_income_statements(payload: Mapping[str, object]) -> list[IncomeStatement]:
    return [
        IncomeStatement(
            period_end=_date_field(row, "period_end"),
            filing_date=_optional_date(row.get("filing_date")),
            revenue=_optional_float(row.get("revenue")),
            gross_profit=_optional_float(row.get("gross_profit")),
            operating_income=_optional_float(row.get("operating_income")),
            net_income=_optional_float(
                row.get("net_income_loss_attributable_common_shareholders")
            ),
            diluted_eps=_optional_float(row.get("diluted_earnings_per_share")),
            diluted_shares=_optional_float(row.get("diluted_shares_outstanding")),
        )
        for row in _results(payload)
    ]


def parse_balance_sheets(payload: Mapping[str, object]) -> list[BalanceSheet]:
    return [
        BalanceSheet(
            period_end=_date_field(row, "period_end"),
            filing_date=_optional_date(row.get("filing_date")),
            total_equity=_optional_float(
                row.get("total_equity_attributable_to_parent") or row.get("total_equity")
            ),
            total_current_assets=_optional_float(row.get("total_current_assets")),
            total_current_liabilities=_optional_float(row.get("total_current_liabilities")),
            debt_current=_optional_float(row.get("debt_current")),
            long_term_debt=_optional_float(
                row.get("long_term_debt_and_capital_lease_obligations")
            ),
        )
        for row in _results(payload)
    ]


def parse_cash_flow_statements(payload: Mapping[str, object]) -> list[CashFlowStatement]:
    return [
        CashFlowStatement(
            period_end=_date_field(row, "period_end"),
            filing_date=_optional_date(row.get("filing_date")),
            operating_cash_flow=_optional_float(
                row.get("net_cash_from_operating_activities")
            ),
            capital_expenditures=_optional_float(
                row.get("purchase_of_property_plant_and_equipment")
            ),
        )
        for row in _results(payload)
    ]


def merge_fundamentals(
    incomes: Sequence[IncomeStatement],
    balances: Sequence[BalanceSheet],
    cashflows: Sequence[CashFlowStatement],
    close_on_or_before: Mapping[date, float] | None = None,
) -> list[PeriodFundamentals]:
    """Join the three statements on period_end into per-period metrics.

    *incomes* drives the period list (TTM rows). *close_on_or_before* maps a
    filing_date to the last daily close at or before that date; absent price
    data simply leaves market_cap/P-E as None (the snapshot renders '-').
    Returns newest-first.
    """
    rows = sorted(incomes, key=lambda r: r.period_end, reverse=True)
    balance_by_end = {b.period_end: b for b in balances}
    cash_by_end = {c.period_end: c for c in cashflows}

    out: list[PeriodFundamentals] = []
    for i, inc in enumerate(rows):
        bal = balance_by_end.get(inc.period_end)
        cf = cash_by_end.get(inc.period_end)

        prior = rows[i + YOY_OFFSET] if i + YOY_OFFSET < len(rows) else None
        revenue_growth = _ratio(
            (inc.revenue - prior.revenue) if inc.revenue is not None and prior is not None and prior.revenue is not None else None,
            prior.revenue if prior is not None else None,
        )

        price = None
        if close_on_or_before is not None and inc.filing_date is not None:
            price = close_on_or_before.get(inc.filing_date)

        market_cap = (
            price * inc.diluted_shares
            if price is not None and inc.diluted_shares
            else None
        )
        pe = (
            price / inc.diluted_eps
            if price is not None and inc.diluted_eps
            else None
        )

        total_debt = _sum_present(
            bal.debt_current if bal else None,
            bal.long_term_debt if bal else None,
        )
        fcf = _sum_present(
            cf.operating_cash_flow if cf else None,
            -cf.capital_expenditures
            if cf is not None and cf.capital_expenditures is not None
            else None,
        )

        out.append(
            PeriodFundamentals(
                report_period=inc.period_end.isoformat(),
                filing_date=inc.filing_date.isoformat() if inc.filing_date else None,
                market_cap=market_cap,
                price_to_earnings_ratio=pe,
                return_on_equity=_ratio(inc.net_income, bal.total_equity if bal else None),
                gross_margin=_ratio(inc.gross_profit, inc.revenue),
                operating_margin=_ratio(inc.operating_income, inc.revenue),
                net_margin=_ratio(inc.net_income, inc.revenue),
                debt_to_equity=_ratio(total_debt, bal.total_equity if bal else None),
                current_ratio=_ratio(
                    bal.total_current_assets if bal else None,
                    bal.total_current_liabilities if bal else None,
                ),
                revenue_growth=revenue_growth,
                earnings_per_share=inc.diluted_eps,
                book_value_per_share=_ratio(
                    bal.total_equity if bal else None, inc.diluted_shares
                ),
                free_cash_flow_per_share=_ratio(fcf, inc.diluted_shares),
            )
        )
    return out


def build_price_lookup(
    filing_dates: Sequence[date],
    closes_by_date: Mapping[date, float],
) -> dict[date, float]:
    """For each filing date, the last daily close at or before it.

    Filings land on any calendar day (often after hours or on non-trading
    days); walk back up to a week to find the preceding session's close.
    """
    if not closes_by_date:
        return {}
    trading_days = sorted(closes_by_date)
    lookup: dict[date, float] = {}
    for filed in filing_dates:
        candidates = [d for d in trading_days if d <= filed]
        if candidates:
            lookup[filed] = closes_by_date[candidates[-1]]
    return lookup


# ----------------------------------------------------------------------
# Field helpers
# ----------------------------------------------------------------------


def _results(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    results = payload.get("results")
    if results is None:
        return []
    if not isinstance(results, list):
        raise TypeError(f"Massive results is not a list: {type(results).__name__}")
    out = []
    for row in results:
        if not isinstance(row, Mapping):
            raise TypeError(f"Massive result row is not an object: {type(row).__name__}")
        out.append(row)
    return out


def _date_field(row: Mapping[str, object], key: str) -> date:
    value = row.get(key)
    if not isinstance(value, str):
        raise TypeError(f"Massive {key} missing or not a string: {value!r}")
    return date.fromisoformat(value)


def _optional_date(value: object) -> date | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise TypeError(f"Massive date is not a string: {value!r}")
    return date.fromisoformat(value)


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"Massive numeric field has type {type(value).__name__}: {value!r}")
    return float(value)


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _sum_present(*values: float | None) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) if present else None
