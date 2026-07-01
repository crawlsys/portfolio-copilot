"""Order spec construction for the Schwab adapter.

Isolates the schwab-py order builders (``schwab.orders.equities``) so that
spec construction is unit-testable without a live client, and so the
application layer never imports schwab-py directly.

A *spec* is a plain ``dict`` — the exact JSON body Schwab's
``/accounts/{hash}/orders`` endpoint expects. Examples:

    {"orderType": "MARKET", "session": "NORMAL", "duration": "DAY",
     "orderLegCollection": [{"instruction": "BUY",
       "instrument": {"assetType": "EQUITY", "symbol": "VTI"},
       "quantity": 12}],
     "orderStrategyType": "SINGLE"}

Dollar-amount orders (``--usd``) are converted to whole-share quantities by
the use case using a live quote; this module only deals in known quantities.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from schwab.orders.common import Duration, Session
from schwab.orders.equities import (
    equity_buy_limit,
    equity_buy_market,
    equity_sell_limit,
    equity_sell_market,
)

from trading.domain.execution.types import OrderSide, OrderType, TimeInForce

if TYPE_CHECKING:
    from schwab.orders.common import OrderBuilder


def build_equity_spec(
    symbol: str,
    side: OrderSide,
    quantity: Decimal,
    order_type: OrderType,
    limit_price: Decimal | None = None,
) -> dict[str, object]:
    """Build a Schwab equity order spec dict.

    Args:
        symbol: Equity ticker, e.g. ``"VTI"``.
        side: BUY or SELL (and the to-open/to-close variants for shorting).
        quantity: Share count, positive, integer-valued for equities.
        order_type: MARKET or LIMIT. LIMIT requires ``limit_price``.
        limit_price: Required for LIMIT orders; ignored for MARKET.

    Returns:
        The order spec dict ready for ``client.place_order``/``preview_order``.

    Raises:
        ValueError: on an unsupported combination (e.g. LIMIT with no price,
            non-integer equity quantity).
    """
    qty = _validate_quantity(quantity)

    if order_type is OrderType.MARKET:
        builder = _market_builder(symbol, side, qty)
    elif order_type is OrderType.LIMIT:
        if limit_price is None:
            raise ValueError("LIMIT orders require a limit_price")
        builder = _limit_builder(symbol, side, qty, limit_price)
    else:
        raise ValueError(
            f"Unsupported order type for equities: {order_type!r}. "
            "Only MARKET and LIMIT are supported."
        )

    return dict(
        builder.set_session(Session.NORMAL)
        .set_duration(Duration.DAY)
        .build()
    )


# ---- internals ---------------------------------------------------------------

def _validate_quantity(quantity: Decimal) -> int:
    """Equities trade in whole shares. Reject fractional quantities."""
    if quantity <= 0:
        raise ValueError(f"Quantity must be positive, got {quantity}")
    qty_int = int(quantity)
    if Decimal(qty_int) != quantity:
        raise ValueError(
            f"Equity orders require whole-share quantities, got {quantity}"
        )
    return qty_int


def _market_builder(symbol: str, side: OrderSide, qty: int) -> OrderBuilder:
    """Select the right market builder by side."""
    if side in (OrderSide.BUY,):
        return equity_buy_market(symbol, qty)
    if side in (OrderSide.SELL,):
        return equity_sell_market(symbol, qty)
    if side is OrderSide.BUY_TO_OPEN:
        return equity_buy_market(symbol, qty)
    if side is OrderSide.BUY_TO_CLOSE:
        return equity_buy_market(symbol, qty)
    if side is OrderSide.SELL_TO_OPEN:
        return equity_sell_short_market_builder(symbol, qty)
    if side is OrderSide.SELL_TO_CLOSE:
        return equity_sell_market(symbol, qty)
    raise ValueError(f"Unsupported side: {side!r}")


def _limit_builder(symbol: str, side: OrderSide, qty: int, price: Decimal) -> OrderBuilder:
    """Select the right limit builder by side."""
    if side in (OrderSide.BUY, OrderSide.BUY_TO_OPEN, OrderSide.BUY_TO_CLOSE):
        return equity_buy_limit(symbol, qty, str(price))
    if side in (OrderSide.SELL, OrderSide.SELL_TO_CLOSE):
        return equity_sell_limit(symbol, qty, str(price))
    if side is OrderSide.SELL_TO_OPEN:
        return equity_sell_short_limit_builder(symbol, qty, price)
    raise ValueError(f"Unsupported side for limit: {side!r}")


def equity_sell_short_market_builder(symbol: str, qty: int) -> OrderBuilder:
    """Build a sell-short market order (sell_to_open for equities)."""
    from schwab.orders.common import EquityInstruction, EquityInstrument  # noqa: PLC0415

    from schwab.orders.common import (  # noqa: PLC0415
        OrderBuilder,
        OrderType,
    )

    return (
        OrderBuilder()
        .add_equity_leg(EquityInstruction.SELL_SHORT, EquityInstrument(symbol), qty)
        .set_order_type(OrderType.MARKET)
    )


def equity_sell_short_limit_builder(symbol: str, qty: int, price: Decimal) -> OrderBuilder:
    """Build a sell-short limit order."""
    from schwab.orders.common import (  # noqa: PLC0415
        EquityInstruction,
        EquityInstrument,
        OrderBuilder,
        OrderType,
    )

    return (
        OrderBuilder()
        .add_equity_leg(EquityInstruction.SELL_SHORT, EquityInstrument(symbol), qty)
        .set_order_type(OrderType.LIMIT)
        .set_price(str(price))
    )
