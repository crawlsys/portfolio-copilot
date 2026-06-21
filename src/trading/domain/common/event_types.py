"""Event type catalog and aggregate type identifiers.

Event names are past-tense integration facts, versioned (`.v1` suffix).
New fields are optional or require a new schema_version (`.v2`).

Execution events are DEFINED but NEVER PRODUCED in v1 — see spec §Non-goals.
They exist here so the type system has them when the Execution context is
implemented (post-backtest validation).
"""
from __future__ import annotations

from enum import StrEnum


class EventType(StrEnum):
    # Portfolio
    POSITION_RECONCILED = "portfolio.position_reconciled.v1"
    POSITION_DRIFT_DETECTED = "portfolio.position_drift_detected.v1"
    ACCOUNT_SNAPSHOT_TAKEN = "portfolio.account_snapshot_taken.v1"

    # Market data
    BAR_CLOSED = "market_data.bar_closed.v1"
    REGIME_CHANGED = "market_data.regime_changed.v1"
    GAP_DETECTED = "market_data.gap_detected.v1"
    OPTION_CHAIN_SNAPSHOT_TAKEN = "market_data.option_chain_snapshot_taken.v1"

    # Congressional
    TRADE_DISCLOSURE_RECEIVED = "congressional.trade_disclosure_received.v1"
    MEMBER_UPDATED = "congressional.member_updated.v1"
    FILING_CORRECTED = "congressional.filing_corrected.v1"

    # Signals
    SIGNAL_PRODUCED = "signals.signal_produced.v1"
    BRIEFING_PRODUCED = "signals.briefing_produced.v1"

    # Execution — DEFINED, NOT PRODUCED in v1. See spec §Execution (stub).
    ORDER_INTENT_CREATED = "execution.order_intent_created.v1"
    APPROVAL_REQUESTED = "execution.approval_requested.v1"
    APPROVAL_GRANTED = "execution.approval_granted.v1"
    APPROVAL_REJECTED = "execution.approval_rejected.v1"
    APPROVAL_EXPIRED = "execution.approval_expired.v1"
    ORDER_SUBMISSION_REQUESTED = "execution.order_submission_requested.v1"
    ORDER_SUBMITTED = "execution.order_submitted.v1"
    ORDER_FILLED = "execution.order_filled.v1"
    ORDER_CANCELLED = "execution.order_cancelled.v1"
    ORDER_REJECTED = "execution.order_rejected.v1"
    BROKER_ORDER_STATUS_SYNCED = "execution.broker_order_status_synced.v1"

    # Audit (cross-cutting)
    AUDIT_EVENT_RECORDED = "audit.audit_event_recorded.v1"


class AggregateType(StrEnum):
    ACCOUNT = "account"
    POSITION = "position"
    TICKER = "ticker"
    BAR = "bar"
    REGIME = "regime"
    MEMBER = "member"
    TRADE_DISCLOSURE = "trade_disclosure"
    SIGNAL = "signal"
    BRIEFING = "briefing"
    # Execution aggregates — defined, unused in v1.
    ORDER_INTENT = "order_intent"
    APPROVAL = "approval"
    ORDER = "order"
    AUDIT = "audit"


def is_produced_in_v1(event_type: EventType) -> bool:
    """True iff this event is actually emitted by the current system.

    Used by tests and the MCP read-only guard to assert the system's scope.
    """
    return event_type not in _DEFERRED_EXECUTION_EVENTS


_DEFERRED_EXECUTION_EVENTS: frozenset[EventType] = frozenset(
    {
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
    }
)
