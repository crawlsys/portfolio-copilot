"""Tests for the event type catalog and the v1 scope guard."""

from __future__ import annotations

from trading.domain import EventType, is_produced_in_v1


class TestEventCatalog:
    def test_portfolio_events_in_v1(self) -> None:
        for et in (
            EventType.POSITION_RECONCILED,
            EventType.POSITION_DRIFT_DETECTED,
            EventType.ACCOUNT_SNAPSHOT_TAKEN,
        ):
            assert is_produced_in_v1(et), f"{et} should be produced in v1"

    def test_market_data_events_in_v1(self) -> None:
        for et in (
            EventType.BAR_CLOSED,
            EventType.REGIME_CHANGED,
            EventType.GAP_DETECTED,
            EventType.OPTION_CHAIN_SNAPSHOT_TAKEN,
        ):
            assert is_produced_in_v1(et)

    def test_congressional_events_in_v1(self) -> None:
        for et in (
            EventType.TRADE_DISCLOSURE_RECEIVED,
            EventType.MEMBER_UPDATED,
            EventType.FILING_CORRECTED,
        ):
            assert is_produced_in_v1(et)

    def test_signals_events_in_v1(self) -> None:
        assert is_produced_in_v1(EventType.SIGNAL_PRODUCED)
        assert is_produced_in_v1(EventType.BRIEFING_PRODUCED)

    def test_audit_event_in_v1(self) -> None:
        assert is_produced_in_v1(EventType.AUDIT_EVENT_RECORDED)


class TestDeferredExecutionEvents:
    """The execution events must EXIST (so the catalog is complete) but be
    flagged as NOT produced in v1. This is the spec's central scope promise.
    """

    DEFERRED = (
        EventType.ORDER_INTENT_CREATED,
        EventType.APPROVAL_REQUESTED,
        EventType.APPROVAL_GRANTED,
        EventType.APPROVAL_REJECTED,
        EventType.APPROVAL_EXPIRED,
        EventType.ORDER_SUBMISSION_REQUESTED,
        EventType.ORDER_SUBMITTED,
        EventType.ORDER_FILLED,
        EventType.ORDER_CANCELLED,
        EventType.ORDER_REJECTED,
        EventType.BROKER_ORDER_STATUS_SYNCED,
    )

    def test_all_defined(self) -> None:
        """Every deferred event has a value (not skipped or TODO)."""
        for et in self.DEFERRED:
            assert et.value.endswith(".v1"), f"{et} missing version suffix"

    def test_none_produced_in_v1(self) -> None:
        for et in self.DEFERRED:
            assert not is_produced_in_v1(et), (
                f"{et} is produced in v1 — this violates the spec's non-goals "
                "(no live trade execution). If you intended to add execution, "
                "see spec §Execution (stub) and update is_produced_in_v1."
            )

    def test_event_string_format(self) -> None:
        """Every event follows {context}.{name}.v{N} — stable for downstream parsers."""
        for et in EventType:
            parts = et.value.split(".")
            assert len(parts) == 3, f"{et} doesn't match context.name.vN: {et.value}"
            context, name, version = parts
            assert context, f"{et} missing context"
            assert name, f"{et} missing name"
            assert version.startswith("v") and version[1:].isdigit(), (
                f"{et} version not vN: {version}"
            )
