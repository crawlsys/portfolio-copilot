"""Tests for domain entities — Portfolio, Congressional, Signals."""
from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime
from decimal import Decimal

from trading.domain import (
    AccountType,
    AssetClass,
    Briefing,
    BrokerAccount,
    Chamber,
    FilingId,
    Horizon,
    Member,
    MemberId,
    Money,
    Party,
    Position,
    Signal,
    SignalId,
    SignalKind,
    Symbol,
    TradeDisclosure,
    TransactionType,
)

# --- Position ----------------------------------------------------------------


class TestPosition:
    def _make(self, qty: Decimal) -> Position:
        return Position(
            account_id="acct1",
            symbol=Symbol("AAPL"),
            quantity=qty,
            average_cost=Money.usd("150"),
            market_value=Money.usd(str(Decimal("100") * qty)),
            unrealized_pnl=Money.usd("0"),
            as_of=datetime(2026, 6, 21, tzinfo=UTC),
        )

    def test_long_is_long(self) -> None:
        assert self._make(Decimal("100")).is_long

    def test_short_is_short(self) -> None:
        assert self._make(Decimal("-100")).is_short

    def test_zero_is_closed(self) -> None:
        assert self._make(Decimal("0")).is_closed
        assert not self._make(Decimal("0")).is_long


# --- BrokerAccount -----------------------------------------------------------


class TestBrokerAccount:
    def test_minimal_account(self) -> None:
        acct = BrokerAccount(
            account_id="hash123",
            nickname="Taxable",
            masked_schwab_id="****1234",
            account_type=AccountType.MARGIN,
            margin_enabled=True,
        )
        assert acct.allowed_instruments == frozenset({AssetClass.EQUITY})  # default
        assert acct.max_order_size is None


# --- TradeDisclosure ---------------------------------------------------------


class TestTradeDisclosure:
    def test_lag_days(self) -> None:
        d = TradeDisclosure(
            filing_id=FilingId("F123"),
            member_id=MemberId("M001"),
            member_name="Jane Doe",
            symbol=Symbol("NVDA"),
            asset_description="NVIDIA Corp",
            transaction_type=TransactionType.PURCHASE,
            transaction_date=date(2026, 5, 1),
            disclosure_date=date(2026, 5, 31),
        )
        assert d.lag_days == 30

    def test_unlisted_asset_allows_none_symbol(self) -> None:
        """Congress sometimes discloses non-tickered assets (municipal bonds, etc.)."""
        d = TradeDisclosure(
            filing_id=FilingId("F124"),
            member_id=MemberId("M001"),
            member_name="Jane Doe",
            symbol=None,
            asset_description="Some muni bond fund",
            transaction_type=TransactionType.PURCHASE,
            transaction_date=date(2026, 5, 1),
            disclosure_date=date(2026, 5, 30),
        )
        assert d.symbol is None


# --- Signal ------------------------------------------------------------------


class TestSignal:
    def test_signal_does_not_have_action_field(self) -> None:
        """Spec invariant: a Signal is a scored observation, not a trade recommendation.

        If someone adds a `buy/sell/hold` action field, this test fails. That
        would violate the spec's §Non-goals (no LLM-driven trade proposals).
        """
        field_names = {f.name for f in dataclasses.fields(Signal)}
        forbidden = {"action", "recommendation", "trade_action"}
        overlap = field_names & forbidden
        assert not overlap, (
            f"Signal must not have trade-action fields; found {overlap}. "
            "Spec §Non-goals: 'No LLM-driven trade proposals.'"
        )

    def test_construct_minimal_signal(self) -> None:
        Signal(
            signal_id=SignalId("s1"),
            source_event_ids=(),
            kind=SignalKind.CONGRESS_TRADE,
            symbol=Symbol("LMT"),
            score=Decimal("0.72"),
            confidence=Decimal("0.55"),
            horizon=Horizon.SWING,
            thesis="3 Armed Services members bought LMT last week",
            features={"source": "quiver"},
            observed_at=datetime(2026, 6, 21, tzinfo=UTC),
        )


# --- Briefing ----------------------------------------------------------------


class TestBriefing:
    def test_briefing_does_not_have_action_field(self) -> None:
        """Briefing surfaces observations; never proposes specific trades."""
        field_names = {f.name for f in dataclasses.fields(Briefing)}
        forbidden = {"recommended_action", "recommended_trades", "buy_list", "sell_list"}
        overlap = field_names & forbidden
        assert not overlap, f"Briefing must not have trade-list fields; found {overlap}"


# --- Member ------------------------------------------------------------------


class TestMember:
    def test_member_with_committees(self) -> None:
        m = Member(
            member_id=MemberId("M001"),
            name="Jane Doe",
            chamber=Chamber.HOUSE,
            party=Party.DEMOCRAT,
            state="CA",
            committees=frozenset({"Armed Services", "Appropriations"}),
        )
        assert "Armed Services" in m.committees
