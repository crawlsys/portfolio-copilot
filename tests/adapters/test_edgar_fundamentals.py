"""SEC company-facts TTM and ratio computation (pure, no network)."""

from __future__ import annotations

from datetime import date

import pytest

from trading.adapters.edgar.fundamentals import company_facts_to_fundamentals


def _row(
    end: str,
    filed: str,
    value: float,
    *,
    form: str = "10-Q",
    start: str = "2024-01-01",
    fy: int = 2024,
    fp: str = "Q1",
) -> dict[str, object]:
    return {
        "start": start,
        "end": end,
        "filed": filed,
        "form": form,
        "fy": fy,
        "fp": fp,
        "val": value,
    }


def _concept(unit: str, rows: list[dict[str, object]]) -> dict[str, object]:
    return {"units": {unit: rows}}


def _payload() -> dict[str, object]:
    quarters = [
        ("2024-03-31", "2024-04-25", 100.0, "Q1"),
        ("2024-06-30", "2024-07-25", 220.0, "Q2"),
        ("2024-09-30", "2024-10-25", 360.0, "Q3"),
    ]
    revenue = [_row(end, filed, val, fp=fp) for end, filed, val, fp in quarters]
    revenue.append(
        _row(
            "2024-12-31",
            "2025-02-01",
            520.0,
            form="10-K",
            fp="FY",
        )
    )
    revenue.append(_row("2025-03-31", "2025-04-25", 130.0, start="2025-01-01", fy=2025))
    return {
        "facts": {
            "us-gaap": {
                "Revenues": _concept("USD", revenue),
                "GrossProfit": _concept("USD", [{**r, "val": float(r["val"]) / 2} for r in revenue]),
                "OperatingIncomeLoss": _concept(
                    "USD", [{**r, "val": float(r["val"]) / 4} for r in revenue]
                ),
                "NetIncomeLoss": _concept(
                    "USD", [{**r, "val": float(r["val"]) / 5} for r in revenue]
                ),
                "EarningsPerShareDiluted": _concept(
                    "USD/shares", [{**r, "val": float(r["val"]) / 100} for r in revenue]
                ),
                "WeightedAverageNumberOfDilutedSharesOutstanding": _concept(
                    "shares", [{**r, "val": 10.0} for r in revenue]
                ),
                "NetCashProvidedByUsedInOperatingActivities": _concept(
                    "USD", [{**r, "val": float(r["val"]) * 0.3} for r in revenue]
                ),
                "PaymentsToAcquirePropertyPlantAndEquipment": _concept(
                    "USD", [{**r, "val": float(r["val"]) * 0.05} for r in revenue]
                ),
                "StockholdersEquity": _concept(
                    "USD",
                    [_row(str(r["end"]), str(r["filed"]), 200.0) for r in revenue],
                ),
                "AssetsCurrent": _concept(
                    "USD", [_row(str(r["end"]), str(r["filed"]), 120.0) for r in revenue]
                ),
                "LiabilitiesCurrent": _concept(
                    "USD", [_row(str(r["end"]), str(r["filed"]), 60.0) for r in revenue]
                ),
                "LongTermDebtNoncurrent": _concept(
                    "USD", [_row(str(r["end"]), str(r["filed"]), 50.0) for r in revenue]
                ),
                "DebtCurrent": _concept(
                    "USD", [_row(str(r["end"]), str(r["filed"]), 10.0) for r in revenue]
                ),
            }
        }
    }


def test_builds_ttm_and_ratios_from_cumulative_quarters() -> None:
    rows = company_facts_to_fundamentals(_payload(), date(2025, 5, 1))
    assert [r.report_period for r in rows[:2]] == ["2025-03-31", "2024-12-31"]
    latest = rows[0]
    # Discrete quarters are 100, 120, 140, 160, 130; latest TTM = 550.
    assert latest.net_margin == pytest.approx(0.2)
    assert latest.gross_margin == pytest.approx(0.5)
    assert latest.current_ratio == pytest.approx(2.0)
    assert latest.debt_to_equity == pytest.approx(0.3)
    assert latest.book_value_per_share == pytest.approx(20.0)
    assert latest.free_cash_flow_per_share == pytest.approx(13.75)


def test_filters_future_filings_and_orders_newest_first() -> None:
    rows = company_facts_to_fundamentals(_payload(), date(2025, 2, 2))
    assert rows
    assert rows[0].report_period == "2024-12-31"
    assert all(r.filing_date is not None and r.filing_date <= "2025-02-02" for r in rows)
    assert [r.report_period for r in rows] == sorted(
        (r.report_period for r in rows), reverse=True
    )


def test_uses_revenue_tag_fallback() -> None:
    payload = _payload()
    gaap = payload["facts"]["us-gaap"]  # type: ignore[index]
    gaap["SalesRevenueNet"] = gaap.pop("Revenues")  # type: ignore[union-attr]
    assert company_facts_to_fundamentals(payload, date(2025, 5, 1))
