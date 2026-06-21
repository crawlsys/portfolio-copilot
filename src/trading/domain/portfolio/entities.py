"""Portfolio context entities.

Source of truth for what the user owns. Reconciled against Schwab read-only;
never written by the user or the agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum, auto

from trading.domain.common.value_objects import AccountType, AssetClass, Money, Symbol


class DriftKind(Enum):
    """How local position diverged from broker."""

    QUANTITY = auto()
    COST_BASIS = auto()
    MISSING_LOCAL = auto()  # broker has position, local doesn't
    MISSING_BROKER = auto()  # local has position, broker doesn't


@dataclass(frozen=True, slots=True)
class BrokerAccount:
    """A Schwab account. Multi-account is first-class — the user has taxable + IRA + cash/T-bill.

    `max_order_size` and `allowed_instruments` are config-driven today and
    informational. They are NOT enforced in v1 (no execution context). When
    execution lands they become hard constraints in the order submit path.
    """

    account_id: str  # Schwab account hash
    nickname: str  # human label, e.g. "Taxable", "Roth IRA"
    masked_schwab_id: str  # last 4, e.g. "****1234"
    account_type: AccountType
    margin_enabled: bool = False
    allowed_instruments: frozenset[AssetClass] = field(
        default_factory=lambda: frozenset({AssetClass.EQUITY})
    )
    max_order_size: Money | None = None


@dataclass(frozen=True, slots=True)
class Position:
    """A single holding: one symbol in one account.

    Reconciled against Schwab. Local state is for fast reads + historical
    snapshots; Schwab is authoritative. `OrderFilled` events (when execution
    lands) are authoritative for position changes; `PositionReconciled` is
    drift detection only.
    """

    account_id: str
    symbol: Symbol
    quantity: Decimal  # long positive, short negative
    average_cost: Money  # per-share cost basis
    market_value: Money  # quantity * current price
    unrealized_pnl: Money  # market_value - (quantity * average_cost)
    as_of: datetime  # when this state was observed

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        return self.quantity < 0

    @property
    def is_closed(self) -> bool:
        return self.quantity == 0


@dataclass(frozen=True, slots=True)
class Account:
    """An account snapshot — balances plus current positions."""

    account_id: str
    cash: Money
    market_value: Money  # sum of position market values
    net_liquidation: Money  # cash + market_value (simplified)
    buying_power: Money
    margin_balance: Money | None = None
    day_pnl: Money | None = None
    positions: tuple[Position, ...] = ()
    as_of: datetime | None = None
