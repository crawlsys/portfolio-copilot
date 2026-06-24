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


POSITIONS = [
    _Pos("GLW", Decimal("665"), Decimal("127570"), Decimal("93268")),
    _Pos("TSLA", Decimal("300"), Decimal("114855"), Decimal("23000")),
    _Pos("MA", Decimal("30"), Decimal("14553"), Decimal("-387")),
]
TOTAL = sum((p.mv for p in POSITIONS), Decimal("0"))
DISC = [_Disc("Nancy Pelosi", "INTC", "PURCHASE", 1000001, 5000000)]
INDIV = _Account(
    name="Individual",
    managed=False,
    cash=Decimal("183316.28"),
    positions=[_Pos("T", Decimal("300"), Decimal("6845.97"), Decimal("0"))],
)


def test_template_digest_marks_managed_and_self_directed_cash() -> None:
    md = _template_digest(POSITIONS, TOTAL, DISC, [], "183316.28", joint_managed=True)
    assert "broker-managed, hold-only" in md
    assert "Cash to deploy (self-directed): **$183,316**" in md
    assert "## Action of the Day" in md


def test_template_push_leads_with_action() -> None:
    push = _template_push(date(2026, 6, 24), DISC, [])
    assert push.startswith("📊 2026-06-24 — Action: HOLD.")


def test_build_context_marks_managed_account_hold_only() -> None:
    ctx = _build_context(
        date(2026, 6, 24), POSITIONS, TOTAL, DISC, [], "unknown",
        "183316.28", INDIV, joint_managed=True,
    )
    # managed joint must be flagged hold-only / non-tradeable
    assert "HOLD-ONLY" in ctx
    assert "NOT tradeable" in ctx
    # real cash from the self-directed account, not a constant
    assert "CASH TO DEPLOY (self-directed account): $183,316" in ctx
    assert "Individual (SELF-DIRECTED" in ctx and "T 300" in ctx
    assert "Nancy Pelosi" in ctx and "INTC" in ctx


def test_build_context_individual_absent_is_handled() -> None:
    ctx = _build_context(
        date(2026, 6, 24), POSITIONS, TOTAL, DISC, [], "unknown",
        "200000", None, joint_managed=False,
    )
    assert "Individual (self-directed): not loaded." in ctx
