"""Unit tests for the digest's pure builders (no DB / no network)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from trading.application.signals.generate_digest import (
    _Account,
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


# Synthetic fixtures — not real holdings.
POSITIONS = [
    _Pos("AAPL", Decimal("100"), Decimal("19000"), Decimal("7000")),
    _Pos("VOO", Decimal("40"), Decimal("21000"), Decimal("3000")),
    _Pos("KO", Decimal("50"), Decimal("3000"), Decimal("-200")),
]
TOTAL = sum((p.mv for p in POSITIONS), Decimal("0"))
DISC = [_Disc("Example Member", "INTC", "PURCHASE", 1000001, 5000000)]
INDIV = _Account(
    name="Individual",
    managed=False,
    cash=Decimal("25000.00"),
    positions=[_Pos("MSFT", Decimal("10"), Decimal("4500"), Decimal("0"))],
)


def test_template_digest_marks_managed_and_self_directed_cash() -> None:
    md = _template_digest(POSITIONS, TOTAL, DISC, [], "25000", joint_managed=True)
    assert "broker-managed, hold-only" in md
    assert "Cash to deploy (self-directed): **$25,000**" in md
    assert "## Action of the Day" in md


def test_template_push_leads_with_action() -> None:
    push = _template_push(date(2026, 6, 24), DISC, [])
    assert push.startswith("📊 2026-06-24 — Action: HOLD.")


def test_build_context_marks_managed_account_hold_only() -> None:
    ctx = _build_context(
        date(2026, 6, 24), POSITIONS, TOTAL, DISC, [], "unknown",
        "25000", INDIV, joint_managed=True,
    )
    # managed joint must be flagged hold-only / non-tradeable
    assert "HOLD-ONLY" in ctx
    assert "NOT tradeable" in ctx
    # real cash from the self-directed account, not a constant
    assert "CASH TO DEPLOY (self-directed account): $25,000" in ctx
    assert "Individual (SELF-DIRECTED" in ctx and "MSFT 10" in ctx
    assert "Example Member" in ctx and "INTC" in ctx


def test_build_context_individual_absent_is_handled() -> None:
    ctx = _build_context(
        date(2026, 6, 24), POSITIONS, TOTAL, DISC, [], "unknown",
        "50000", None, joint_managed=False,
    )
    assert "Individual (self-directed): not loaded." in ctx
