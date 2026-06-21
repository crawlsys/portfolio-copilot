"""Signals context entities.

Scores observations and produces the daily briefing. **No `Recommendation`
type in v1** — the original "actionable buy/sell" was cut because the alpha
isn't validated (see spec §Strategy review). Replaced with `Signal` (scored
observation) and `Briefing` (daily output).

When execution eventually lands, a `Recommendation` type may be added — but
only after a backtest validates a thesis (spec §11). Don't pre-build it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import NewType
from uuid import UUID

from trading.domain.common.value_objects import Horizon, SignalKind, Symbol

SignalId = NewType("SignalId", str)
BriefingId = NewType("BriefingId", str)


@dataclass(frozen=True, slots=True)
class Signal:
    """A scored observation over some source event(s).

    A signal is NOT a trade recommendation. It's a notable pattern worth
    surfacing in the daily briefing. Examples:
    - "3 members of Armed Services committee bought LMT in the last week"
    - "VIX crossed 30; regime flipped to RISK_OFF"
    - "Your NVDA position has drifted 8% above target weight"

    Scoring is heuristic + LLM-assisted, but the LLM never produces a "buy/sell"
    action — that's explicitly out of scope for v1.
    """

    signal_id: SignalId
    source_event_ids: tuple[UUID, ...]
    kind: SignalKind
    symbol: Symbol | None  # None for market-regime / portfolio-level signals
    score: Decimal  # 0..1 normalized
    confidence: Decimal  # 0..1 — how sure we are the pattern is real
    horizon: Horizon
    thesis: str  # human-readable explanation
    features: dict[str, str]  # flattened provenance: {"source": "quiver", ...}
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class Briefing:
    """The daily AI briefing. Summary + references, no 'buy this' actions.

    `summary_markdown` is the full text; if it's large (>64KB) the body lives
    in Garage and `body_blob_key` points to it.
    """

    briefing_id: BriefingId
    briefing_date: date
    period_start: datetime
    period_end: datetime
    summary_markdown: str
    push_excerpt: str  # the short text pushed to phone
    referenced_signal_ids: tuple[SignalId, ...] = ()
    referenced_disclosure_ids: tuple[str, ...] = ()
    body_blob_key: str | None = None
    generated_at: datetime | None = None
