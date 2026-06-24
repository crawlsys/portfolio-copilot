"""Unit tests for the digest's pure builders (no DB / no network)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from trading.application.signals.generate_digest import (
    _Pos,
    _build_context,
    _template_digest,
    _template_push,
)


class _Disc:
    """Minimal stand-in for TradeDisclosureRow."""

    def __init__(self, member: str, symbol: str, ttype: str, lo: int, hi: int) -> None:
        self.member_name = member
        self.symbol = symbol
        self.transaction_type = ttype
        self.amount_range_low = lo
        self.amount_range_high = hi
        self.transaction_date = datetime(2026, 5, 29, tzinfo=UTC)
        self.disclosure_date = datetime(2026, 6, 23, tzinfo=UTC)


POSITIONS = [
    _Pos("GLW", Decimal("665"), Decimal("127570"), Decimal("93268")),
    _Pos("TSLA", Decimal("300"), Decimal("114855"), Decimal("23000")),
    _Pos("MA", Decimal("30"), Decimal("14553"), Decimal("-387")),
]
TOTAL = sum((p.mv for p in POSITIONS), Decimal("0"))
DISC = [_Disc("Nancy Pelosi", "INTC", "PURCHASE", 1000001, 5000000)]


def test_template_digest_has_required_sections_and_concentration() -> None:
    md = _template_digest(POSITIONS, TOTAL, DISC, [], "200000")
    assert "## Portfolio Snapshot" in md
    assert "## Action of the Day" in md
    assert "**HOLD**" in md  # fallback is always an explicit HOLD
    assert "GLW" in md and "$127,570" in md
    assert "$200,000" in md  # cash to deploy rendered


def test_template_push_leads_with_action() -> None:
    push = _template_push(date(2026, 6, 24), DISC, [])
    assert push.startswith("📊 2026-06-24 — Action: HOLD.")
    assert "1 disclosure(s)" in push


def test_build_context_includes_positions_disclosures_and_overlaps() -> None:
    overlaps = [_Disc("Jared Moskowitz", "GLW", "PURCHASE", 1001, 15000)]
    ctx = _build_context(date(2026, 6, 24), POSITIONS, TOTAL, DISC, overlaps, "unknown", "200000")
    assert "Equity book value: $256,978" in ctx
    assert "Uninvested CASH available to deploy: $200,000" in ctx
    assert "Nancy Pelosi" in ctx and "INTC" in ctx
    assert "OVERLAPPING HELD TICKERS: GLW" in ctx
    assert "$1,000,001–$5,000,000" in ctx
