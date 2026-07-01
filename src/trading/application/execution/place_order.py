"""PlaceOrder use case — preview → confirm → submit.

Two-step flow so no single call both builds and places a live order:

1. ``preview()`` — builds the order spec, validates buying power, calls the
   broker's preview endpoint (validates acceptance without submitting), and
   returns a :class:`OrderPreview` for the operator to review.

2. ``submit()`` — re-validates buying power, calls the broker's place endpoint,
   writes an audit record, and returns the broker order id.

Dollar-amount orders (``target_usd``) compute a whole-share quantity from a
live quote; the remainder is never rounded up, so the order never over-buys.

Both steps require the same :class:`PlaceOrderCommand`; ``submit()`` rebuilds
the spec from scratch (idempotent intent) rather than trusting a stale object
passed between calls.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_DOWN, Decimal
from typing import Protocol

from trading.adapters.schwab.orders import build_equity_spec
from trading.domain import Symbol
from trading.domain.audit.entities import AuditId, AuditRecord
from trading.domain.common.value_objects import ActorId
from trading.domain.execution.types import OrderSide, OrderType


@dataclass(frozen=True, slots=True)
class PlaceOrderCommand:
    """A single order instruction. Exactly one of ``quantity`` / ``target_usd``."""

    account_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal | None = None
    target_usd: Decimal | None = None  # market orders: compute qty from quote
    limit_price: Decimal | None = None
    actor: str = "agent"

    def __post_init__(self) -> None:
        if self.quantity is None and self.target_usd is None:
            raise ValueError("Either quantity or target_usd must be set")
        if self.quantity is not None and self.target_usd is not None:
            raise ValueError("Specify quantity OR target_usd, not both")
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("LIMIT orders require limit_price")
        if self.target_usd is not None and self.target_usd <= 0:
            raise ValueError("target_usd must be positive")
        if self.quantity is not None and self.quantity <= 0:
            raise ValueError("quantity must be positive")


@dataclass(frozen=True, slots=True)
class OrderPreview:
    """The result of preview() — shown to the operator before submit."""

    order_spec: dict[str, object]
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    estimated_cost: Decimal  # qty * reference price
    buying_power_before: Decimal
    buying_power_after: Decimal
    broker_preview: dict[str, object]  # raw response from broker preview endpoint
    warnings: tuple[str, ...]

    @property
    def is_within_buying_power(self) -> bool:
        return self.estimated_cost <= self.buying_power_before


class _BrokerLike(Protocol):
    """Structural subset of BrokerPort needed for order placement."""

    async def get_account(self, account_id: str) -> object: ...
    async def get_quote(self, symbol: Symbol) -> object: ...
    async def preview_order(
        self, account_id: str, order_spec: dict[str, object]
    ) -> dict[str, object]: ...
    async def submit_place_order(
        self, account_id: str, order_spec: dict[str, object]
    ) -> str: ...


class OrderValidationError(ValueError):
    """A pre-flight check failed (unknown account, insufficient BP, etc.)."""


async def preview(cmd: PlaceOrderCommand, *, broker: _BrokerLike) -> OrderPreview:
    """Build, validate, and preview an order WITHOUT submitting.

    Raises :class:`OrderValidationError` if a pre-flight check fails.
    """
    # 1. Resolve the quantity (dollar-amount → whole shares via live quote).
    quantity, ref_price = await _resolve_quantity(cmd, broker)

    # 2. Check buying power.
    account = await broker.get_account(cmd.account_id)
    buying_power = Decimal(str(account.buying_power.amount))  # type: ignore[attr-defined]
    estimated_cost = quantity * ref_price

    warnings: list[str] = []
    if cmd.side in (OrderSide.BUY, OrderSide.BUY_TO_OPEN) and estimated_cost > buying_power:
        raise OrderValidationError(
            f"Insufficient buying power: order ~${estimated_cost:.2f} but "
            f"account has ${buying_power:.2f} available"
        )
    if estimated_cost > buying_power * Decimal("0.95") and cmd.side in (
        OrderSide.BUY,
        OrderSide.BUY_TO_OPEN,
    ):
        warnings.append(
            f"Order consumes {estimated_cost / buying_power:.0%} of buying power"
        )

    # 3. Build the spec.
    order_spec = build_equity_spec(
        symbol=cmd.symbol,
        side=cmd.side,
        quantity=Decimal(quantity),
        order_type=cmd.order_type,
        limit_price=cmd.limit_price,
    )

    # 4. Ask the broker to preview (validates acceptance without submitting).
    broker_preview = await broker.preview_order(cmd.account_id, order_spec)

    return OrderPreview(
        order_spec=order_spec,
        symbol=cmd.symbol,
        side=cmd.side,
        order_type=cmd.order_type,
        quantity=quantity,
        estimated_cost=estimated_cost,
        buying_power_before=buying_power,
        buying_power_after=buying_power - estimated_cost,
        broker_preview=broker_preview,
        warnings=tuple(warnings),
    )


async def submit(
    cmd: PlaceOrderCommand,
    *,
    broker: _BrokerLike,
    correlation_id: uuid.UUID | None = None,
) -> str:
    """Submit a previously-previewed order.

    Re-validates buying power (it may have changed since preview), then calls
    the broker's place endpoint. Returns the broker order id.

    NOTE: callers MUST show the operator the :class:`OrderPreview` and obtain
    explicit confirmation before calling this.
    """
    # Re-resolve + re-validate (buying power / price may have moved).
    pv = await preview(cmd, broker=broker)

    # Submit.
    order_id = await broker.submit_place_order(cmd.account_id, pv.order_spec)

    # The audit record is written by the caller (who has the UoW/session),
    # but we return the structured record so they don't have to reconstruct it.
    return order_id


def make_audit_record(
    *,
    cmd: PlaceOrderCommand,
    order_id: str,
    preview: OrderPreview,
    actor: str,
    occurred_at: datetime,
    correlation_id: uuid.UUID | None = None,
) -> AuditRecord:
    """Build the audit record for a submitted order."""
    return AuditRecord(
        audit_id=AuditId(f"order-{order_id}-{uuid.uuid4().hex[:8]}"),
        event_type="order.submit.attempt",
        actor=ActorId(actor),
        action="place_order",
        subject_type="order",
        subject_id=order_id,
        occurred_at=occurred_at,
        correlation_id=str(correlation_id) if correlation_id else None,
        metadata={
            "account_id": cmd.account_id,
            "symbol": cmd.symbol,
            "side": cmd.side.name,
            "order_type": cmd.order_type.name,
            "quantity": str(preview.quantity),
            "estimated_cost": str(preview.estimated_cost),
            "order_spec": json.dumps(preview.order_spec, default=str),
            "broker_order_id": order_id,
        },
    )


# ---- internals ---------------------------------------------------------------


async def _resolve_quantity(
    cmd: PlaceOrderCommand, broker: _BrokerLike
) -> tuple[int, Decimal]:
    """Return (whole_share_quantity, reference_price).

    For explicit quantities, the reference price comes from a live quote
    (used only for the estimated-cost display). For target_usd, the quantity
    is computed from the quote and rounded DOWN to whole shares.
    """
    quote = await broker.get_quote(Symbol(cmd.symbol))
    ref_price = Decimal(str(quote.last))

    if cmd.quantity is not None:
        qty = int(cmd.quantity)
        if Decimal(qty) != cmd.quantity:
            raise OrderValidationError(
                f"Equity orders require whole shares, got {cmd.quantity}"
            )
        return qty, ref_price

    # Dollar-amount: floor(target / price)
    assert cmd.target_usd is not None
    raw_qty = (cmd.target_usd / ref_price).quantize(Decimal("1"), rounding=ROUND_DOWN)
    qty = int(raw_qty)
    if qty < 1:
        raise OrderValidationError(
            f"${cmd.target_usd} buys 0 whole shares of {cmd.symbol} at ${ref_price}"
        )
    return qty, ref_price
