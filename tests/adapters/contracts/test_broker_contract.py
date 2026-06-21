"""Contract tests for BrokerPort.

The point: any implementation that claims to be a BrokerPort must satisfy
this contract. Today there's only FakeBroker; when SchwabBrokerAdapter
arrives, it gets parametrized into these same tests.

Also enforces the spec's central scope promise: the protocol has NO trading
methods. If someone adds place_order/cancel_order to BrokerPort, these
tests fail — which is the desired alarm.
"""

from __future__ import annotations

import inspect
from decimal import Decimal
from pathlib import Path

import pytest

from trading.adapters.fake.broker import FakeBroker, make_default_fake_broker
from trading.adapters.ports.broker import BrokerPort
from trading.domain import AccountType, AssetClass, Money, Symbol


@pytest.fixture()
def fake() -> FakeBroker:
    """A deterministic sample broker — independent of holdings.json.

    Tests in this file assert specific shapes/values, so they need a known
    fixture rather than whatever the user's real holdings happen to be.
    """
    broker = FakeBroker()
    broker.add_account(
        account_id="paper-001",
        nickname="Paper Taxable",
        masked_schwab_id="****0001",
        account_type=AccountType.MARGIN,
        margin_enabled=True,
        cash=Money.usd("200000"),
    )
    broker.set_position(
        account_id="paper-001",
        symbol=Symbol("AAPL"),
        quantity=Decimal("100"),
        average_cost=Money.usd("150.00"),
        market_value=Money.usd("17500.00"),
    )
    broker.set_position(
        account_id="paper-001",
        symbol=Symbol("NVDA"),
        quantity=Decimal("50"),
        average_cost=Money.usd("400.00"),
        market_value=Money.usd("60000.00"),
    )
    broker.set_quote(Symbol("AAPL"), bid=Decimal("174.50"), ask=Decimal("175.50"))
    broker.set_quote(Symbol("NVDA"), bid=Decimal("1195.00"), ask=Decimal("1205.00"))
    return broker


# --- Contract: FakeBroker satisfies BrokerPort shape ------------------------


def test_fake_broker_satisfies_broker_port(fake: FakeBroker) -> None:
    """FakeBroker must structurally satisfy BrokerPort."""
    assert isinstance(fake, BrokerPort), (
        "FakeBroker must structurally satisfy BrokerPort. If this fails, "
        "FakeBroker is missing a method that BrokerPort declares."
    )


@pytest.mark.asyncio
async def test_get_accounts_returns_tuple(fake: FakeBroker) -> None:
    accounts = await fake.get_accounts()
    assert isinstance(accounts, tuple)
    assert len(accounts) >= 1
    assert all(hasattr(a, "account_id") and hasattr(a, "nickname") for a in accounts)


@pytest.mark.asyncio
async def test_get_account_returns_snapshot(fake: FakeBroker) -> None:
    acct = await fake.get_account("paper-001")
    assert acct.account_id == "paper-001"
    assert acct.cash.amount >= 0
    assert len(acct.positions) >= 1


@pytest.mark.asyncio
async def test_get_positions_returns_position_with_pnl(fake: FakeBroker) -> None:
    positions = await fake.get_positions("paper-001")
    assert len(positions) >= 1
    p = positions[0]
    assert p.symbol.ticker  # non-empty
    assert p.quantity != 0
    assert p.unrealized_pnl.currency == "USD"


@pytest.mark.asyncio
async def test_get_quote_returns_snapshot(fake: FakeBroker) -> None:
    q = await fake.get_quote(Symbol("AAPL"))
    assert q.bid > 0
    assert q.ask >= q.bid
    assert q.last > 0


@pytest.mark.asyncio
async def test_stream_quotes_yields_existing(fake: FakeBroker) -> None:
    """stream_quotes yields one quote per known symbol, then ends."""
    seen: list[str] = []
    async for q in fake.stream_quotes((Symbol("AAPL"), Symbol("NVDA"))):
        seen.append(q.symbol.ticker)
    assert "AAPL" in seen
    assert "NVDA" in seen


@pytest.mark.asyncio
async def test_unknown_account_raises(fake: FakeBroker) -> None:
    """Reads on unknown account IDs must raise — never silently return empty."""
    with pytest.raises(KeyError):
        await fake.get_account("does-not-exist")
    with pytest.raises(KeyError):
        await fake.get_positions("does-not-exist")


@pytest.mark.asyncio
async def test_unknown_quote_raises(fake: FakeBroker) -> None:
    with pytest.raises(KeyError):
        await fake.get_quote(Symbol("UNKNWN"))


# --- Scope guard: NO trading methods on the v1 protocol ----------------------


class TestNoTradingMethodsInV1:
    """Spec §Non-goals: no live order placement, no LLM-driven trade proposals.

    If anyone adds `place_order`, `cancel_order`, or any method whose name
    suggests trading to BrokerPort, these tests fail loudly. That's the alarm
    that says 'you've wandered into deferred Execution territory — see spec.'
    """

    def _broker_port_methods(self) -> set[str]:
        return {name for name, _ in inspect.getmembers(BrokerPort, predicate=inspect.isfunction)}

    def test_no_place_order_method(self) -> None:
        methods = self._broker_port_methods()
        assert "place_order" not in methods, (
            "BrokerPort.place_order exists — this violates spec §Non-goals. "
            "If execution is being activated, see spec §Execution (stub) "
            "and apply every money-path red-team fix (§10)."
        )

    def test_no_cancel_order_method(self) -> None:
        methods = self._broker_port_methods()
        assert "cancel_order" not in methods, (
            "BrokerPort.cancel_order exists — same violation as place_order."
        )

    def test_no_method_with_trade_action_verb(self) -> None:
        """Defensive: catch any future trading method by name pattern."""
        methods = self._broker_port_methods()
        trade_verbs = {"buy", "sell", "trade", "submit", "execute", "approve"}
        for name in methods:
            verb = name.split("_")[0]
            assert verb not in trade_verbs, (
                f"BrokerPort.{name} looks like a trading method — "
                f"verb '{verb}' is in the forbidden set {trade_verbs}. "
                "See spec §Non-goals."
            )


# --- Seeded data sanity (also exercises the seeding helpers) -----------------


@pytest.mark.asyncio
async def test_default_fake_broker_loads_real_holdings_when_present() -> None:
    """When data/holdings.json exists, the default broker loads it.

    Tolerates the JSON being absent (CI without the user's statement); in
    that case asserts the sample fallback account exists instead.
    """

    holdings_path = Path(__file__).resolve().parents[3] / "data" / "holdings.json"
    broker = make_default_fake_broker()
    accounts = await broker.get_accounts()
    assert len(accounts) >= 1
    acct = await broker.get_account(accounts[0].account_id)
    if holdings_path.exists():
        assert len(acct.positions) >= 10, (
            f"Expected >=10 positions from holdings.json, got {len(acct.positions)}"
        )
    else:
        assert len(acct.positions) >= 1


@pytest.mark.asyncio
async def test_set_position_recomputes_market_value() -> None:
    broker = FakeBroker()
    broker.add_account("a1", "Test", "****1", cash=Money.usd("100000"))
    broker.set_position(
        account_id="a1",
        symbol=Symbol("MSFT"),
        quantity=Decimal("100"),
        average_cost=Money.usd("300"),
        market_value=Money.usd("40000"),
    )
    acct = await broker.get_account("a1")
    # net_liquidation = 100k cash + 40k market value
    assert acct.net_liquidation.amount == Decimal("140000")
    assert acct.market_value.amount == Decimal("40000")


@pytest.mark.asyncio
async def test_set_position_supports_option_symbol() -> None:
    """Options use OCC format; ensure FakeBroker handles them."""
    broker = FakeBroker()
    broker.add_account("a1", "Test", "****1")
    opt = Symbol("AAPL260621C00150000", asset_class=AssetClass.OPTION)
    broker.set_position(
        account_id="a1",
        symbol=opt,
        quantity=Decimal("1"),
        average_cost=Money.usd("2.50"),
        market_value=Money.usd("3.00"),
    )
    positions = await broker.get_positions("a1")
    assert len(positions) == 1
    assert positions[0].symbol.asset_class == AssetClass.OPTION
