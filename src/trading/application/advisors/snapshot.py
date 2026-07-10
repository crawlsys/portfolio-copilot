"""Point-in-time fundamentals snapshot — the shared input for advisor agents.

A `FundamentalsSnapshot` is everything an advisor is allowed to know about a
company as of a given date: a history of per-period metrics (each row provably
public by `as_of` — the data layer filters on filing_date, never on the fiscal
period end, which precedes public availability by 3-6 weeks) plus a few
derived aggregates computed here in Python so the LLM reasons over facts
instead of re-deriving arithmetic.

The snapshot is pure data: build it once, hash it, feed it to any persona.
`content_hash` is the LLM cache key — an advisor only re-reasons when a new
filing changes its snapshot.

Ported from ai-hedge-fund v2 features/snapshot.py (MIT), adapted to tracker's
async ports.
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

# An advisor can't say anything defensible about a company with less history
# than this (one year of trailing-twelve-month rows).
MIN_PERIODS = 4

DEFAULT_PERIODS = 20


class InsufficientDataError(ValueError):
    """Not enough point-in-time history to build a snapshot."""


class PeriodFundamentals(BaseModel):
    """One reporting period's key metrics, compacted for prompting."""

    report_period: str
    filing_date: str | None = None
    market_cap: float | None = None
    price_to_earnings_ratio: float | None = None
    return_on_equity: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    debt_to_equity: float | None = None
    current_ratio: float | None = None
    revenue_growth: float | None = None
    earnings_per_share: float | None = None
    book_value_per_share: float | None = None
    free_cash_flow_per_share: float | None = None


@runtime_checkable
class FundamentalsPort(Protocol):
    """Point-in-time fundamentals source.

    Implementations MUST filter on filing_date <= as_of (public knowledge
    only) and return periods newest-first. Infrastructure failures raise;
    "no data exists" returns an empty list.
    """

    async def get_fundamentals_history(
        self, ticker: str, as_of: date, limit: int = DEFAULT_PERIODS
    ) -> list[PeriodFundamentals]: ...


class FundamentalsSnapshot(BaseModel):
    """What an advisor may know about *ticker* as of *as_of*. Newest first."""

    ticker: str
    as_of: str
    periods: list[PeriodFundamentals]

    # Derived aggregates (computed in build_snapshot, not by the LLM)
    roe_avg: float | None = None
    net_margin_avg: float | None = None
    gross_margin_trend: float | None = None  # latest minus oldest
    bvps_cagr: float | None = None
    debt_to_equity_latest: float | None = None
    market_cap_latest: float | None = None

    @property
    def content_hash(self) -> str:
        """Stable hash of the snapshot's content — the LLM cache key."""
        canonical = self.model_dump_json()
        return hashlib.sha256(canonical.encode()).hexdigest()[:24]

    def render(self) -> str:
        """Compact text block for the LLM prompt."""
        lines = [
            f"Company: {self.ticker}",
            f"As of: {self.as_of} (all data below was publicly filed by this date)",
            "",
            "Summary:",
            f"  Market cap (latest filed): {_fmt(self.market_cap_latest)}",
            f"  ROE avg: {_fmt(self.roe_avg)}  |  Net margin avg: {_fmt(self.net_margin_avg)}",
            f"  Gross margin trend (latest-oldest): {_fmt(self.gross_margin_trend)}",
            f"  Book value/share CAGR: {_fmt(self.bvps_cagr)}",
            f"  Debt/equity (latest): {_fmt(self.debt_to_equity_latest)}",
            "",
            "History (trailing-twelve-month periods, newest first):",
            "period | filed | mktcap | P/E | ROE | gross_m | op_m | net_m | D/E "
            "| curr | rev_gr | EPS | BVPS | FCF/sh",
        ]
        for p in self.periods:
            lines.append(
                f"{p.report_period} | {p.filing_date or '?'} | {_fmt(p.market_cap)} "
                f"| {_fmt(p.price_to_earnings_ratio)} | {_fmt(p.return_on_equity)} "
                f"| {_fmt(p.gross_margin)} | {_fmt(p.operating_margin)} "
                f"| {_fmt(p.net_margin)} | {_fmt(p.debt_to_equity)} "
                f"| {_fmt(p.current_ratio)} | {_fmt(p.revenue_growth)} "
                f"| {_fmt(p.earnings_per_share)} | {_fmt(p.book_value_per_share)} "
                f"| {_fmt(p.free_cash_flow_per_share)}"
            )
        return "\n".join(lines)


async def build_snapshot(
    ticker: str,
    as_of: date,
    fundamentals: FundamentalsPort,
    periods: int = DEFAULT_PERIODS,
) -> FundamentalsSnapshot:
    """Build the point-in-time snapshot for (ticker, as_of).

    Raises InsufficientDataError if fewer than MIN_PERIODS filed periods exist.
    Data-layer failures propagate (fail loud) — a broken snapshot must never
    silently become a neutral view.
    """
    rows = await fundamentals.get_fundamentals_history(ticker, as_of, limit=periods)
    if len(rows) < MIN_PERIODS:
        raise InsufficientDataError(
            f"{ticker} as of {as_of}: only {len(rows)} filed periods (need {MIN_PERIODS})"
        )

    return FundamentalsSnapshot(
        ticker=ticker,
        as_of=as_of.isoformat(),
        periods=rows,
        roe_avg=_avg([p.return_on_equity for p in rows]),
        net_margin_avg=_avg([p.net_margin for p in rows]),
        gross_margin_trend=_trend([p.gross_margin for p in rows]),
        bvps_cagr=_cagr([p.book_value_per_share for p in rows]),
        debt_to_equity_latest=rows[0].debt_to_equity,
        market_cap_latest=rows[0].market_cap,
    )


def _fmt(value: float | None) -> str:
    if value is None:
        return "-"
    if abs(value) >= 1_000_000:
        return f"{value:,.0f}"
    return f"{value:.3f}"


def _avg(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def _trend(values: list[float | None]) -> float | None:
    """Latest minus oldest (values are newest-first)."""
    present = [v for v in values if v is not None]
    if len(present) < 2:
        return None
    return present[0] - present[-1]


def _cagr(values: list[float | None]) -> float | None:
    """Compound annual growth from oldest to latest (values newest-first,
    one quarter apart)."""
    present = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(present) < 2:
        return None
    latest_i, latest = present[0]
    oldest_i, oldest = present[-1]
    quarters = oldest_i - latest_i
    if quarters <= 0 or oldest <= 0 or latest <= 0:
        return None
    years = quarters / 4.0
    return float((latest / oldest) ** (1.0 / years)) - 1.0
