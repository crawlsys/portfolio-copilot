"""Shared domain value types. Frozen, hashable, validated.

These are the atoms every bounded context uses. No I/O, no third-party deps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum, auto
from typing import NewType

# --- Identifier newtypes -----------------------------------------------------
# Today these are bare strings; they're seams for future richer types
# (e.g. ActorId gains permissions when multi-user/Auth lands — see spec §Non-goals).
ActorId = NewType("ActorId", str)
CorrelationId = NewType("CorrelationId", str)
BlobKey = NewType("BlobKey", str)


# --- Enums -------------------------------------------------------------------


class AssetClass(Enum):
    EQUITY = auto()
    OPTION = auto()
    # Non-equity instruments held in a brokerage account: treasuries/bonds
    # (CUSIP-identified), mutual funds, money-market, REITs, preferreds. These
    # don't satisfy the equity ticker regex and aren't options; tickers/CUSIPs
    # for them are accepted as-is (no format validation) so their market value
    # is never silently dropped from net liquidation.
    FIXED_INCOME = auto()
    FUND = auto()


class AccountType(Enum):
    """Schwab account classification. Drives what's displayable / (later) tradeable."""

    TAXABLE = auto()
    IRA = auto()  # traditional
    ROTH_IRA = auto()
    MARGIN = auto()
    CASH = auto()
    UNKNOWN = auto()


class Chamber(Enum):
    HOUSE = auto()
    SENATE = auto()


class Party(Enum):
    DEMOCRAT = auto()
    REPUBLICAN = auto()
    INDEPENDENT = auto()
    UNKNOWN = auto()


class TransactionType(Enum):
    """Congressional disclosure transaction types."""

    PURCHASE = auto()
    SALE = auto()
    SALE_PARTIAL = auto()  # sale of partial position
    EXCHANGE = auto()
    OTHER = auto()


class SignalKind(Enum):
    CONGRESS_TRADE = auto()
    MARKET_REGIME = auto()
    PORTFOLIO_DRIFT = auto()
    EARNINGS = auto()
    MANUAL = auto()


class Horizon(Enum):
    INTRADAY = auto()
    SWING = auto()
    POSITION = auto()


class Severity(Enum):
    INFO = auto()
    WARNING = auto()
    CRITICAL = auto()


# --- Frozen value objects ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class Money:
    """Decimal-precise money with explicit currency. Max 4 decimal places.

    Money is never constructed from floats — only Decimal or int cents.
    """

    amount: Decimal
    currency: str = "USD"

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError(
                f"Money.amount must be Decimal, got {type(self.amount).__name__}. "
                "Never use floats — they lose precision."
            )
        if self.amount.as_tuple().exponent < -4:  # type: ignore[operator]
            raise ValueError(f"Money precision exceeds 4 decimal places: {self.amount}")
        if not self.currency or len(self.currency) != 3:
            raise ValueError(f"currency must be a 3-letter ISO code, got {self.currency!r}")

    @classmethod
    def usd(cls, amount: str | Decimal) -> Money:
        return cls(amount=Decimal(str(amount)), currency="USD")

    @classmethod
    def zero(cls, currency: str = "USD") -> Money:
        return cls(amount=Decimal("0"), currency=currency)

    def __add__(self, other: Money) -> Money:
        self._check_currency(other)
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check_currency(other)
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def __mul__(self, factor: Decimal | int) -> Money:
        # Quantize to 4dp — multiplication can produce more decimal places
        # than either operand (e.g. 150.50 * 100 = 15050.00000), which would
        # violate Money's 4dp invariant on construction.
        product = (self.amount * Decimal(str(factor))).quantize(Decimal("0.0001"))
        return Money(amount=product, currency=self.currency)

    __rmul__ = __mul__

    def is_negative(self) -> bool:
        return self.amount < 0

    def is_zero(self) -> bool:
        return self.amount == 0

    def _check_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise ValueError(f"Currency mismatch: {self.currency} vs {other.currency}")


@dataclass(frozen=True, slots=True)
class Symbol:
    """A tradeable symbol. Equities are plain tickers; options use OCC format.

    OCC option symbol format: {UNDERLYING}{YYMMDD}{C/P}{STRIKE*1000 zero-padded 8}
    e.g. NVDA240315C00080000 = NVDA call expiring 2024-03-15 at strike $80.
    """

    ticker: str
    asset_class: AssetClass = AssetClass.EQUITY

    def __post_init__(self) -> None:
        if not self.ticker:
            raise ValueError("ticker must not be empty")
        if self.asset_class is AssetClass.EQUITY and not _EQUITY_RE.match(self.ticker):
            raise ValueError(
                f"Invalid equity ticker: {self.ticker!r}. "
                "Use 1-6 uppercase A-Z, optionally with '.' or '-'."
            )
        if self.asset_class is AssetClass.OPTION and not _OPTION_RE.match(self.ticker):
            raise ValueError(
                f"Invalid OCC option symbol: {self.ticker!r}. "
                "Expected format: UNDERLYING{YYMMDD}{C|P}{8-digit strike*1000}"
            )

    def __str__(self) -> str:
        return self.ticker


_EQUITY_RE = re.compile(r"^[A-Z]{1,6}([.\-][A-Z]{1,4})?$")
_OPTION_RE = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")


@dataclass(frozen=True, slots=True)
class DateRange:
    """Inclusive [start, end] date range."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"DateRange end < start: {self.end} < {self.start}")
