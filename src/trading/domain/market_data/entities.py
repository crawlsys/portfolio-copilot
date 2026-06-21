"""Market data context entities.

Cacheable, low-fidelity-truth. A Quote is "someone said the price was X at T,"
not authoritative. Decoupled from Portfolio so a bad tick never corrupts books.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from trading.domain.common.value_objects import AssetClass, Symbol


@dataclass(frozen=True, slots=True)
class Quote:
    symbol: Symbol
    bid: Decimal
    ask: Decimal
    last: Decimal
    timestamp: datetime
    volume: int | None = None

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid


@dataclass(frozen=True, slots=True)
class Bar:
    """OHLCV bar over a timeframe."""

    symbol: Symbol
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    opened_at: datetime
    closed_at: datetime
    timeframe: str   # "1m", "5m", "1h", "1d"
    vwap: Decimal | None = None


class MarketRegime(Enum):
    """High-level market state. Drives briefing and (future) signal confidence."""

    RISK_ON = "risk_on"        # bullish breadth, low vol, advancing
    RISK_OFF = "risk_off"      # defensive, high vol, declining
    NEUTRAL = "neutral"
    TRANSITION = "transition"  # regime just changed, unclear direction


# Note: AssetClass imported above is re-exported here for callers that reach
# through market_data for value types. Prefer importing from common directly.
__all__ = ["AssetClass", "Bar", "MarketRegime", "Quote", "Symbol"]
