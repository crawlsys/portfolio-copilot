"""Tests for the order spec builder + PlaceOrder validation.

These cover the pure logic (spec construction, quantity resolution, buying-
power checks) without touching the live Schwab API. The broker is stubbed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from trading.adapters.schwab.orders import build_equity_spec
from trading.application.execution.place_order import (
    OrderValidationError,
    PlaceOrderCommand,
    preview,
)
from trading.domain import Money, Symbol
from trading.domain.execution.types import OrderSide, OrderType


# ---- spec builder -----------------------------------------------------------


def test_market_buy_spec() -> None:
    spec = build_equity_spec("VTI", OrderSide.BUY, Decimal(12), OrderType.MARKET)
    assert spec["orderType"] == "MARKET"
    legs = spec["orderLegCollection"]
    assert len(legs) == 1
    assert legs[0]["instruction"] == "BUY"
    assert legs[0]["instrument"]["symbol"] == "VTI"
    assert legs[0]["quantity"] == 12
    assert spec["session"] == "NORMAL"
    assert spec["duration"] == "DAY"


def test_limit_buy_spec_has_price() -> None:
    spec = build_equity_spec(
        "AAPL", OrderSide.BUY, Decimal(100), OrderType.LIMIT, limit_price=Decimal("230.50")
    )
    assert spec["orderType"] == "LIMIT"
    assert spec["price"] == "230.50"


def test_limit_requires_price() -> None:
    with pytest.raises(ValueError, match="limit_price"):
        build_equity_spec("VTI", OrderSide.BUY, Decimal(10), OrderType.LIMIT)


def test_sell_spec_instruction() -> None:
    spec = build_equity_spec("T", OrderSide.SELL, Decimal(50), OrderType.MARKET)
    assert spec["orderLegCollection"][0]["instruction"] == "SELL"


def test_rejects_fractional_shares() -> None:
    with pytest.raises(ValueError, match="whole-share"):
        build_equity_spec("VTI", OrderSide.BUY, Decimal("12.5"), OrderType.MARKET)


def test_rejects_nonpositive_quantity() -> None:
    with pytest.raises(ValueError, match="positive"):
        build_equity_spec("VTI", OrderSide.BUY, Decimal(0), OrderType.MARKET)


def test_rejects_unsupported_order_type() -> None:
    with pytest.raises(ValueError, match="Unsupported order type"):
        build_equity_spec("VTI", OrderSide.BUY, Decimal(10), OrderType.STOP)


# ---- command validation -----------------------------------------------------


def test_command_requires_qty_or_usd() -> None:
    with pytest.raises(ValueError, match="quantity or target_usd"):
        PlaceOrderCommand(
            account_id="x", symbol="VTI", side=OrderSide.BUY, order_type=OrderType.MARKET
        )


def test_command_rejects_both_qty_and_usd() -> None:
    with pytest.raises(ValueError, match="not both"):
        PlaceOrderCommand(
            account_id="x", symbol="VTI", side=OrderSide.BUY, order_type=OrderType.MARKET,
            quantity=Decimal(10), target_usd=Decimal(3000),
        )


def test_command_limit_requires_price() -> None:
    with pytest.raises(ValueError, match="limit_price"):
        PlaceOrderCommand(
            account_id="x", symbol="VTI", side=OrderSide.BUY, order_type=OrderType.LIMIT,
            quantity=Decimal(10),
        )


# ---- preview validation (stubbed broker) ------------------------------------


@dataclass
class _FakeMoney:
    amount: Decimal


@dataclass
class _FakeAccount:
    buying_power: _FakeMoney


@dataclass
class _FakeQuote:
    last: _FakeMoney


class _StubBroker:
    """Minimal broker stub for preview() tests. Never submits."""

    def __init__(self, *, price: Decimal, buying_power: Decimal) -> None:
        self._price = price
        self._bp = buying_power
        self.submitted = False

    async def get_account(self, account_id: str) -> _FakeAccount:
        return _FakeAccount(buying_power=_FakeMoney(self._bp))

    async def get_quote(self, symbol: Symbol) -> _FakeQuote:
        return _FakeQuote(last=_FakeMoney(self._price))

    async def preview_order(
        self, account_id: str, order_spec: dict[str, object]
    ) -> dict[str, object]:
        return {"accepted": True}

    async def submit_place_order(
        self, account_id: str, order_spec: dict[str, object]
    ) -> str:
        self.submitted = True
        return "ORDER-999"


@pytest.mark.anyio
async def test_preview_usd_rounds_down_to_whole_shares() -> None:
    broker = _StubBroker(price=Decimal("250.00"), buying_power=Decimal("100000"))
    cmd = PlaceOrderCommand(
        account_id="act", symbol="VTI", side=OrderSide.BUY,
        order_type=OrderType.MARKET, target_usd=Decimal("3000"),
    )
    pv = await preview(cmd, broker=broker)  # type: ignore[arg-type]
    # 3000 / 250 = 12 shares exactly
    assert pv.quantity == 12
    assert pv.estimated_cost == Decimal("3000.00")


@pytest.mark.anyio
async def test_preview_usd_floors_when_not_even() -> None:
    broker = _StubBroker(price=Decimal("249.75"), buying_power=Decimal("100000"))
    cmd = PlaceOrderCommand(
        account_id="act", symbol="VTI", side=OrderSide.BUY,
        order_type=OrderType.MARKET, target_usd=Decimal("3000"),
    )
    pv = await preview(cmd, broker=broker)  # type: ignore[arg-type]
    # 3000 / 249.75 = 12.01 → floor to 12
    assert pv.quantity == 12
    assert pv.estimated_cost == 12 * Decimal("249.75")


@pytest.mark.anyio
async def test_preview_rejects_insufficient_buying_power() -> None:
    broker = _StubBroker(price=Decimal("250.00"), buying_power=Decimal("2000"))
    cmd = PlaceOrderCommand(
        account_id="act", symbol="VTI", side=OrderSide.BUY,
        order_type=OrderType.MARKET, target_usd=Decimal("3000"),
    )
    with pytest.raises(OrderValidationError, match="Insufficient buying power"):
        await preview(cmd, broker=broker)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_preview_does_not_submit() -> None:
    broker = _StubBroker(price=Decimal("250.00"), buying_power=Decimal("100000"))
    cmd = PlaceOrderCommand(
        account_id="act", symbol="VTI", side=OrderSide.BUY,
        order_type=OrderType.MARKET, target_usd=Decimal("3000"),
    )
    await preview(cmd, broker=broker)  # type: ignore[arg-type]
    assert broker.submitted is False
