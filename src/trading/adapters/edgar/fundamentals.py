"""Pure SEC company-facts normalization and fundamentals computation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from trading.adapters.massive.fundamentals import (
    BalanceSheet,
    CashFlowStatement,
    IncomeStatement,
    merge_fundamentals,
)
from trading.application.advisors.snapshot import PeriodFundamentals

JsonObject = Mapping[str, object]
_FORMS = {"10-K", "10-K/A", "10-Q"}

_REVENUE = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
)
_EQUITY = (
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
)
_CURRENT_DEBT = ("LongTermDebtCurrent", "DebtCurrent")


@dataclass(frozen=True)
class Fact:
    end: date
    filed: date
    value: float
    form: str
    fiscal_year: int | None
    fiscal_period: str | None
    start: date | None = None


def company_facts_to_fundamentals(
    payload: Mapping[str, object],
    as_of: date,
    close_on_or_before: Mapping[date, float] | None = None,
) -> list[PeriodFundamentals]:
    """Convert an SEC companyfacts document into newest-first TTM metrics."""
    facts = _facts_root(payload)
    flows = {
        "revenue": _concept(facts, "us-gaap", _REVENUE, "USD", as_of),
        "gross": _concept(facts, "us-gaap", ("GrossProfit",), "USD", as_of),
        "operating": _concept(facts, "us-gaap", ("OperatingIncomeLoss",), "USD", as_of),
        "net": _concept(facts, "us-gaap", ("NetIncomeLoss",), "USD", as_of),
        "eps": _concept(facts, "us-gaap", ("EarningsPerShareDiluted",), "USD/shares", as_of),
        "shares": _concept(
            facts,
            "us-gaap",
            ("WeightedAverageNumberOfDilutedSharesOutstanding",),
            "shares",
            as_of,
        )
        or _concept(
            facts,
            "dei",
            ("EntityCommonStockSharesOutstanding",),
            "shares",
            as_of,
        ),
        "ocf": _concept(
            facts,
            "us-gaap",
            ("NetCashProvidedByUsedInOperatingActivities",),
            "USD",
            as_of,
        ),
        "capex": _concept(
            facts,
            "us-gaap",
            ("PaymentsToAcquirePropertyPlantAndEquipment",),
            "USD",
            as_of,
        ),
    }
    annual_ends = {f.end for values in flows.values() for f in values if f.form.startswith("10-K")}
    ends = sorted({f.end for f in flows["revenue"]}, reverse=True)
    incomes: list[IncomeStatement] = []
    cashflows: list[CashFlowStatement] = []
    for end in ends:
        filing = _filing_for_end(flows["revenue"], end)
        if filing is None:
            continue
        incomes.append(
            IncomeStatement(
                period_end=end,
                filing_date=filing,
                revenue=_ttm(flows["revenue"], end, annual_ends),
                gross_profit=_ttm(flows["gross"], end, annual_ends),
                operating_income=_ttm(flows["operating"], end, annual_ends),
                net_income=_ttm(flows["net"], end, annual_ends),
                diluted_eps=_ttm(flows["eps"], end, annual_ends),
                diluted_shares=_ttm_shares(flows["shares"], end),
            )
        )
        cashflows.append(
            CashFlowStatement(
                period_end=end,
                filing_date=filing,
                operating_cash_flow=_ttm(flows["ocf"], end, annual_ends),
                capital_expenditures=_ttm(flows["capex"], end, annual_ends),
            )
        )

    balances = _balances(facts, as_of, ends)
    return merge_fundamentals(incomes, balances, cashflows, close_on_or_before)


def _balances(facts: JsonObject, as_of: date, ends: Sequence[date]) -> list[BalanceSheet]:
    concepts = {
        "equity": _concept(facts, "us-gaap", _EQUITY, "USD", as_of),
        "assets_current": _concept(facts, "us-gaap", ("AssetsCurrent",), "USD", as_of),
        "liabilities_current": _concept(
            facts, "us-gaap", ("LiabilitiesCurrent",), "USD", as_of
        ),
        "debt_current": _concept(facts, "us-gaap", _CURRENT_DEBT, "USD", as_of),
        "debt_long": _concept(facts, "us-gaap", ("LongTermDebtNoncurrent",), "USD", as_of),
    }
    rows = []
    for end in ends:
        selected = {name: _instant(values, end) for name, values in concepts.items()}
        filing_dates = [f.filed for f in selected.values() if f is not None]
        rows.append(
            BalanceSheet(
                period_end=end,
                filing_date=max(filing_dates) if filing_dates else None,
                total_equity=_value(selected["equity"]),
                total_current_assets=_value(selected["assets_current"]),
                total_current_liabilities=_value(selected["liabilities_current"]),
                debt_current=_value(selected["debt_current"]),
                long_term_debt=_value(selected["debt_long"]),
            )
        )
    return rows


def _ttm(facts: Sequence[Fact], end: date, annual_ends: set[date]) -> float | None:
    annual = _annual(facts, end)
    if annual is not None:
        return annual.value
    quarters = _quarters(facts, annual_ends)
    eligible = sorted((e, v) for e, v in quarters.items() if e <= end)
    if not eligible or eligible[-1][0] != end or len(eligible) < 4:
        return None
    return sum(value for _, value in eligible[-4:])


def _ttm_shares(facts: Sequence[Fact], end: date) -> float | None:
    annual = _annual(facts, end)
    if annual is not None:
        return annual.value
    # Weighted-average shares are already a period average, not an additive
    # flow. Average the four reported quarterly/YTD observations rather than
    # differencing them like revenue or cash flow.
    observations = {e: fact.value for e, fact in _one_per_end(facts).items()}
    eligible = sorted((e, v) for e, v in observations.items() if e <= end)
    if not eligible or eligible[-1][0] != end or len(eligible) < 4:
        return None
    return sum(value for _, value in eligible[-4:]) / 4


def _quarters(facts: Sequence[Fact], annual_ends: set[date]) -> dict[date, float]:
    """Normalize YTD 10-Q values into discrete fiscal-quarter values."""
    chosen = _one_per_end(facts)
    out: dict[date, float] = {}
    for end, fact in sorted(chosen.items()):
        if end in annual_ends and fact.form.startswith("10-K"):
            previous = [v for e, v in out.items() if e < end][-3:]
            if len(previous) == 3:
                out[end] = fact.value - sum(previous)
            continue
        prior_ytd = [
            other
            for other in chosen.values()
            if other.end < end
            and other.fiscal_year == fact.fiscal_year
            and other.start == fact.start
            and other.form == "10-Q"
        ]
        out[end] = fact.value - max(prior_ytd, key=lambda f: f.end).value if prior_ytd else fact.value
    return out


def _annual(facts: Sequence[Fact], end: date) -> Fact | None:
    candidates = [f for f in facts if f.end == end and f.form.startswith("10-K")]
    return max(candidates, key=lambda f: f.filed) if candidates else None


def _one_per_end(facts: Sequence[Fact]) -> dict[date, Fact]:
    out: dict[date, Fact] = {}
    for fact in facts:
        current = out.get(fact.end)
        if current is None or fact.filed > current.filed:
            out[fact.end] = fact
    return out


def _instant(facts: Sequence[Fact], end: date) -> Fact | None:
    candidates = [f for f in facts if f.end == end]
    return max(candidates, key=lambda f: f.filed) if candidates else None


def _filing_for_end(facts: Sequence[Fact], end: date) -> date | None:
    selected = _instant(facts, end)
    return selected.filed if selected else None


def _value(fact: Fact | None) -> float | None:
    return fact.value if fact else None


def _facts_root(payload: Mapping[str, object]) -> JsonObject:
    facts = payload.get("facts")
    if not isinstance(facts, Mapping):
        raise TypeError("SEC companyfacts payload has no facts object")
    return facts


def _concept(
    facts: JsonObject,
    namespace: str,
    tags: Sequence[str],
    unit: str,
    as_of: date,
) -> list[Fact]:
    ns = facts.get(namespace)
    if not isinstance(ns, Mapping):
        return []
    result: list[Fact] = []
    covered_ends: set[date] = set()
    for tag in tags:
        concept = ns.get(tag)
        if not isinstance(concept, Mapping):
            continue
        units = concept.get("units")
        if not isinstance(units, Mapping):
            continue
        rows = units.get(unit)
        if not isinstance(rows, list):
            continue
        parsed = [_parse_fact(row) for row in rows if isinstance(row, Mapping)]
        usable = [
            f
            for f in parsed
            if f is not None
            and f.filed <= as_of
            and f.form in _FORMS
            and f.end not in covered_ends
        ]
        result.extend(usable)
        covered_ends.update(f.end for f in usable)
    return result


def _parse_fact(row: Mapping[str, object]) -> Fact | None:
    try:
        end, filed, form, value = row["end"], row["filed"], row["form"], row["val"]
        if not isinstance(end, str) or not isinstance(filed, str) or not isinstance(form, str):
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        fy = row.get("fy")
        fp = row.get("fp")
        start = row.get("start")
        return Fact(
            end=date.fromisoformat(end),
            filed=date.fromisoformat(filed),
            value=float(value),
            form=form,
            fiscal_year=fy if isinstance(fy, int) else None,
            fiscal_period=fp if isinstance(fp, str) else None,
            start=date.fromisoformat(start) if isinstance(start, str) else None,
        )
    except (KeyError, ValueError):
        return None
