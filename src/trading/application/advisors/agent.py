"""AdvisorAgent — base class for persona LLM analysts.

An advisor reasons over a point-in-time FundamentalsSnapshot in a persona's
voice and emits an AdvisorView. The base class owns all machinery; a persona
is just a name + a system prompt.

Failure contract (locked decisions, ported from ai-hedge-fund v2):
- Data-layer errors PROPAGATE (fail loud — a broken snapshot must never
  silently become a neutral view). Callers own building the snapshot.
- LLM call/parse failures ABSTAIN: stance="neutral", confidence=0,
  abstained=True with the reason.
- Every non-abstained view carries the EXACT system/user prompt and raw
  response — the persistence layer stores them (cache + audit trail).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading.application.advisors.llm import LLMClient, extract_json
from trading.application.advisors.snapshot import FundamentalsSnapshot
from trading.domain import Horizon, Signal, SignalId, SignalKind, Symbol

logger = logging.getLogger(__name__)

STANCES = ("bullish", "neutral", "bearish")


@dataclass(frozen=True)
class AdvisorView:
    """One persona's point-in-time view on a ticker."""

    advisor: str
    model: str
    ticker: str
    as_of: str
    snapshot_hash: str
    stance: str  # bullish | neutral | bearish
    confidence: float  # 0-100
    reasoning: str
    system_prompt: str
    user_prompt: str
    raw_response: str
    abstained: bool = False
    abstain_reason: str | None = None

    @property
    def score(self) -> float:
        """Signed conviction in [-1, +1]: sign from stance, magnitude from
        confidence. Neutral/abstained → 0."""
        sign = {"bullish": 1.0, "neutral": 0.0, "bearish": -1.0}[self.stance]
        return sign * self.confidence / 100.0

    def to_signal(self, signal_id: str, observed_at: datetime) -> Signal:
        """Project this view into the domain Signal vocabulary.

        Signal.score is 0..1 (magnitude); direction travels in
        features["stance"] — consistent with Signal being an observation,
        not a trade action.
        """
        return Signal(
            signal_id=SignalId(signal_id),
            source_event_ids=(),
            kind=SignalKind.ADVISOR_VIEW,
            symbol=Symbol(self.ticker),
            score=Decimal(str(self.confidence / 100.0)),
            confidence=Decimal("0") if self.abstained else Decimal("1"),
            horizon=Horizon.POSITION,
            thesis=self.reasoning,
            features={
                "advisor": self.advisor,
                "model": self.model,
                "stance": self.stance,
                "snapshot_hash": self.snapshot_hash,
                "as_of": self.as_of,
            },
            observed_at=observed_at,
        )


class AdvisorAgent:
    """Base for persona advisors. Subclasses define `name` and `get_system_prompt`."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    @property
    def name(self) -> str:
        raise NotImplementedError(f"{type(self).__name__} must define name")

    def get_system_prompt(self) -> str:
        """The persona — every subclass must define its voice."""
        raise NotImplementedError(f"{type(self).__name__} must define get_system_prompt()")

    def build_user_prompt(self, snapshot: FundamentalsSnapshot) -> str:
        """Default user prompt: the rendered snapshot. Override to enrich."""
        return snapshot.render()

    async def form_view(self, snapshot: FundamentalsSnapshot) -> AdvisorView:
        """Form this persona's view on an already-built snapshot."""
        system = self.get_system_prompt()
        user = self.build_user_prompt(snapshot)

        try:
            response = await self._llm.complete(system, user)
        except Exception as exc:
            logger.warning(
                "%s LLM call failed for %s@%s: %s",
                self.name,
                snapshot.ticker,
                snapshot.as_of,
                exc,
            )
            return self._abstain(snapshot, system, user, "", f"LLM call failed: {exc}")

        try:
            stance, confidence, reasoning = self._parse(response)
        except Exception as exc:
            # Keep the raw response — it is the debug trail.
            logger.warning(
                "%s parse failed for %s@%s: %s",
                self.name,
                snapshot.ticker,
                snapshot.as_of,
                exc,
            )
            return self._abstain(snapshot, system, user, response, f"parse failed: {exc}")

        return AdvisorView(
            advisor=self.name,
            model=self._llm.model,
            ticker=snapshot.ticker,
            as_of=snapshot.as_of,
            snapshot_hash=snapshot.content_hash,
            stance=stance,
            confidence=confidence,
            reasoning=reasoning,
            system_prompt=system,
            user_prompt=user,
            raw_response=response,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse(self, response: str) -> tuple[str, float, str]:
        """Extract + validate (stance, confidence, reasoning)."""
        data = extract_json(response)
        stance = str(data.get("signal", "")).lower()
        if stance not in STANCES:
            raise ValueError(f"invalid signal {data.get('signal')!r}")
        confidence = float(data.get("confidence", 0))  # type: ignore[arg-type]
        if not 0 <= confidence <= 100:
            raise ValueError(f"confidence out of range: {confidence}")
        return stance, confidence, str(data.get("reasoning", ""))

    def _abstain(
        self,
        snapshot: FundamentalsSnapshot,
        system: str,
        user: str,
        raw_response: str,
        reason: str,
    ) -> AdvisorView:
        return AdvisorView(
            advisor=self.name,
            model=self._llm.model,
            ticker=snapshot.ticker,
            as_of=snapshot.as_of,
            snapshot_hash=snapshot.content_hash,
            stance="neutral",
            confidence=0.0,
            reasoning=f"abstained: {reason}",
            system_prompt=system,
            user_prompt=user,
            raw_response=raw_response,
            abstained=True,
            abstain_reason=reason,
        )
