"""ClockPort — abstract time. No datetime.now()/utcnow() in domain code.

Critical for testability — tests inject a FrozenClock; the future backtest
injects a HistoricalClock. Real system uses SystemClock.

Also exposes market-hours queries (NYSE open/close, next open) — the domain
needs to know whether it's safe to (eventually) submit orders, and the
daily briefing needs to know if it's a trading day.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol, runtime_checkable


@runtime_checkable
class ClockPort(Protocol):
    """Abstract time + market-hours. Inject at composition time."""

    def now(self) -> datetime:
        """Current UTC datetime."""
        ...

    def today(self) -> date:
        """Current UTC date."""
        ...

    def is_market_open(self, market: str = "NYSE") -> bool:
        """True iff market is in regular trading hours right now."""
        ...

    def next_market_open(self, market: str = "NYSE") -> datetime:
        """Next market open (today if before open, else next trading day)."""
        ...


class SystemClock:
    """Production clock. Reads wall time."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def today(self) -> date:
        return self.now().date()

    def is_market_open(self, market: str = "NYSE") -> bool:
        now = self.now()
        # NYSE: 9:30–16:00 ET, Mon–Fri, excluding holidays (TODO: holiday calendar)
        if now.weekday() >= 5:
            return False
        # Crude ET offset from UTC: -5 (EST) or -4 (EDT). For correctness we'd
        # use zoneinfo; for v1 this is acceptable approximation.
        et_hour = (now.hour - 5) % 24  # EST; FIXME: DST handling
        if et_hour < 9 or et_hour >= 16:
            return False
        return not (et_hour == 9 and now.minute < 30)

    def next_market_open(self, market: str = "NYSE") -> datetime:
        now = self.now()
        # Walk forward to the next 9:30 ET weekday
        candidate = datetime.combine(now.date(), time(14, 30), tzinfo=UTC)  # 9:30 EST
        while candidate <= now or candidate.weekday() >= 5:
            candidate += timedelta(days=1)
            candidate = candidate.replace(hour=14, minute=30)
        return candidate


class FrozenClock:
    """Test clock. Returns a fixed time; advance manually."""

    def __init__(self, fixed: datetime) -> None:
        self._fixed = fixed

    def now(self) -> datetime:
        return self._fixed

    def today(self) -> date:
        return self._fixed.date()

    def is_market_open(self, market: str = "NYSE") -> bool:
        # Default to closed in tests; tests that need it open override.
        return False

    def next_market_open(self, market: str = "NYSE") -> datetime:
        return self._fixed

    def advance(self, delta: timedelta) -> None:
        self._fixed = self._fixed + delta
