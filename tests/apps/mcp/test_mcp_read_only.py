"""MCP read-only scope guard tests.

Ensures all registered tools are read-only (no buy/sell/trade verbs) and —
regression for the handler-overwrite bug — that ONE ListTools request against
the actual server returns every module's tools, not just the last-registered
module's.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import mcp.types as types
import pytest
from apps.common.composition import make_composition
from apps.mcp.server import create_server
from apps.mcp.tools import advisors, all_tools, briefing, congressional, dispatch, market, portfolio

from trading.adapters.fake.broker import FakeBroker
from trading.domain import Money, Symbol

FORBIDDEN_TOOL_VERBS = frozenset(
    {
        "buy",
        "sell",
        "trade",
        "submit",
        "execute",
        "approve",
        "place",
        "cancel",
        "order",
    }
)

ALL_MODULES = (portfolio, congressional, market, briefing, advisors)


def _make_fake_broker() -> FakeBroker:
    broker = FakeBroker()
    broker.add_account(
        account_id="test-001",
        nickname="Test Account",
        masked_schwab_id="****1234",
        cash=Money.usd("50000"),
    )
    broker.set_position(
        account_id="test-001",
        symbol=Symbol("AAPL"),
        quantity=Decimal("100"),
        average_cost=Money.usd("150.00"),
        market_value=Money.usd("17500.00"),
    )
    broker.set_quote(
        Symbol("AAPL"),
        bid=Decimal("174.00"),
        ask=Decimal("176.00"),
    )
    return broker


class TestMCPReadOnly:
    """All MCP tools must be read-only."""

    def test_no_forbidden_verbs_in_tool_names(self) -> None:
        """No tool name may contain buy/sell/trade/submit/execute/approve verbs.

        Derived from the modules' actual TOOLS lists — never a hardcoded
        name list, which is how the registration bug went unnoticed.
        """
        for tool in all_tools():
            name_lower = tool.name.lower()
            for verb in FORBIDDEN_TOOL_VERBS:
                assert verb not in name_lower, (
                    f"Tool '{tool.name}' contains forbidden verb '{verb}'. "
                    "MCP tools must be read-only. Spec §Non-goals."
                )

    def test_tool_names_are_read_prefixed(self) -> None:
        """All tool names must start with get_ or list_ (read operations)."""
        for tool in all_tools():
            assert tool.name.startswith(("get_", "list_")), (
                f"Tool '{tool.name}' does not start with get_ or list_. "
                "Read-only tools should use read-style prefixes."
            )


class TestAllModulesVisible:
    """Regression: apps/mcp/tools modules each used @server.list_tools(),
    and the low-level Server keeps ONE handler per request type — the last
    registration (briefing) replaced the rest, so connected agents saw only
    briefing tools and could not answer portfolio questions."""

    @pytest.fixture
    def server(self) -> Any:
        comp = make_composition(broker_mode="fake", database_url="")
        comp.broker = _make_fake_broker()  # deterministic fixtures
        return create_server(comp)

    @pytest.mark.asyncio
    async def test_single_list_tools_request_returns_every_module(self, server: Any) -> None:
        handler = server.request_handlers[types.ListToolsRequest]
        result = await handler(types.ListToolsRequest(method="tools/list"))
        served = {t.name for t in result.root.tools}

        for module in ALL_MODULES:
            for tool in module.TOOLS:
                assert tool.name in served, (
                    f"{module.__name__}'s tool '{tool.name}' is not served by "
                    "the live ListTools handler — a module registration is "
                    "clobbering the shared handler slot again."
                )

    @pytest.mark.asyncio
    async def test_call_tool_routes_across_modules(self, server: Any) -> None:
        """One CallTool handler must reach tools from different modules."""
        handler = server.request_handlers[types.CallToolRequest]

        for tool_name, expect in (
            ("get_accounts", "test-001"),  # portfolio module
            ("get_quote", "AAPL"),  # market module
        ):
            request = types.CallToolRequest(
                method="tools/call",
                params=types.CallToolRequestParams(
                    name=tool_name,
                    arguments={"symbol": "AAPL"},
                ),
            )
            result = await handler(request)
            assert not result.root.isError
            text = result.root.content[0].text
            assert expect in text, f"{tool_name}: expected {expect!r} in {text!r}"


class TestDispatch:
    """dispatch() routes by name and rejects unknown tools."""

    @pytest.mark.asyncio
    async def test_dispatch_reaches_each_module(self) -> None:
        comp = make_composition(broker_mode="fake", database_url="")
        comp.broker = _make_fake_broker()  # deterministic fixtures

        result = await dispatch("get_accounts", {}, comp)
        assert "test-001" in result[0].text

        result = await dispatch("get_positions", {"account_id": "test-001"}, comp)
        assert "AAPL" in result[0].text

        result = await dispatch("get_quote", {"symbol": "AAPL"}, comp)
        assert "174.00" in result[0].text

        # briefing module with no DB configured answers gracefully
        result = await dispatch("get_latest_briefing", {}, comp)
        assert "Database not configured" in result[0].text

    @pytest.mark.asyncio
    async def test_dispatch_unknown_tool(self) -> None:
        comp = make_composition(broker_mode="fake", database_url="")
        result = await dispatch("get_nonexistent", {}, comp)
        assert "Unknown tool" in result[0].text


class TestPortfolioTools:
    """Portfolio tool return shapes."""

    @pytest.fixture
    def fake_broker(self) -> FakeBroker:
        return _make_fake_broker()

    @pytest.mark.asyncio
    async def test_get_accounts_returns_list(self, fake_broker: FakeBroker) -> None:
        accounts = await fake_broker.get_accounts()
        assert isinstance(accounts, tuple)
        assert len(accounts) == 1
        assert accounts[0].account_id == "test-001"

    @pytest.mark.asyncio
    async def test_get_positions_returns_list(self, fake_broker: FakeBroker) -> None:
        positions = await fake_broker.get_positions("test-001")
        assert isinstance(positions, tuple)
        assert len(positions) == 1
        assert positions[0].symbol.ticker == "AAPL"

    @pytest.mark.asyncio
    async def test_get_account_returns_snapshot(self, fake_broker: FakeBroker) -> None:
        snapshot = await fake_broker.get_account("test-001")
        assert snapshot.account_id == "test-001"
        assert len(snapshot.positions) == 1


class TestMarketTools:
    """Market data tool return shapes."""

    @pytest.fixture
    def fake_broker(self) -> FakeBroker:
        broker = FakeBroker()
        broker.set_quote(
            Symbol("NVDA"),
            bid=Decimal("1000.00"),
            ask=Decimal("1002.00"),
        )
        return broker

    @pytest.mark.asyncio
    async def test_get_quote_returns_quote(self, fake_broker: FakeBroker) -> None:
        quote = await fake_broker.get_quote(Symbol("NVDA"))
        assert quote.symbol.ticker == "NVDA"
        assert quote.bid == Decimal("1000.00")
        assert quote.ask == Decimal("1002.00")

    @pytest.mark.asyncio
    async def test_get_quote_raises_for_unknown(self, fake_broker: FakeBroker) -> None:
        with pytest.raises(KeyError):
            await fake_broker.get_quote(Symbol("XYZ"))
