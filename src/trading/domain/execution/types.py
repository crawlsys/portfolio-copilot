"""Execution lifecycle types — DEFINED, NOT INSTANTIATED in v1.

These exist so the event catalog, OpenAPI schema, and downstream consumers
know the shapes ahead of time. Importing or instantiating any of these in
v1 application code is a bug — the execution context has no implementation.

See `__init__.py` for why this is deferred.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum, auto
from typing import NewType

from trading.domain.common.value_objects import Symbol

# These NewTypes are forward-declared seams. Uninstantiated in v1.
OrderIntentId = NewType("OrderIntentId", str)
OrderId = NewType("OrderId", str)
ApprovalId = NewType("ApprovalId", str)
IdempotencyKey = NewType("IdempotencyKey", str)
BrokerOrderId = NewType("BrokerOrderId", str)
OrderIntentHash = NewType("OrderIntentHash", str)


class _DeferredExecutionTypes:
    """Marker: importing this means you've wandered into deferred territory.

    Instantiating any type below in v1 is a runtime error. Use the
    `is_produced_in_v1` predicate in `event_types.py` to gate event types.
    """

    __slots__ = ()


class OrderSide(Enum):
    BUY = auto()
    SELL = auto()
    BUY_TO_OPEN = auto()
    BUY_TO_CLOSE = auto()
    SELL_TO_OPEN = auto()
    SELL_TO_CLOSE = auto()


class OrderType(Enum):
    MARKET = auto()
    LIMIT = auto()
    STOP = auto()
    STOP_LIMIT = auto()


class TimeInForce(Enum):
    DAY = auto()
    GTC = auto()
    IOC = auto()
    FOK = auto()


@dataclass(frozen=True, slots=True)
class _OrderLeg:
    """A single leg of a (possibly multi-leg) order. Defined for shape only."""

    symbol: Symbol
    side: OrderSide
    quantity: Decimal
    asset_class: str  # AssetClass, but kept as str to avoid forward-imports


@dataclass(frozen=True, slots=True)
class _OrderIntent:
    """User/agent-proposed order awaiting approval. DEFINED, NOT USED in v1.

    This type exists so the event catalog and OpenAPI know its shape.
    See `__init__.py` for the deferral rationale.
    """

    intent_id: OrderIntentId
    account_id: str
    legs: tuple[_OrderLeg, ...]
    order_type: OrderType
    time_in_force: TimeInForce
    limit_price: Decimal | None
    stop_price: Decimal | None
    actor: str
    created_at: datetime
    idempotency_key: IdempotencyKey
    intent_hash: OrderIntentHash
    rationale: str | None = None


# NOTE: ExecutableOrder, Order, Fill are intentionally NOT defined here.
# When execution lands, they require the sealed-type machinery (token gate,
# __reduce__ overrides, etc.) per spec §10. Pre-defining them without that
# machinery would mislead callers into thinking they're usable.
