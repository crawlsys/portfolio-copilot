"""Audit context (cross-cutting).

Append-only record of every significant action. Distinct from the event log:
- event_log: state-reconstruction source of truth (replayable projections)
- audit: who/when/what for compliance, forensics, and operator actions that
  aren't otherwise domain events (kill-switch toggles, reauth, manual replay).

Both are queryable. Audit mirrors every domain event by subscribing to the bus.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import NewType

from trading.domain.common.value_objects import ActorId

AuditId = NewType("AuditId", str)


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """Immutable audit entry."""

    audit_id: AuditId
    event_type: str              # e.g. "order.submit.attempt" (string, not EventType)
    actor: ActorId | None        # None for system-initiated
    action: str                  # e.g. "place_order", "rotate_token", "replay_event"
    subject_type: str            # "order_intent", "briefing", "schwab_token", ...
    subject_id: str
    occurred_at: datetime
    correlation_id: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
