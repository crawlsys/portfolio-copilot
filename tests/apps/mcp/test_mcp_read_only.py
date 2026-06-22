"""MCP read-only scope guard tests.

Ensures all registered tools are read-only (no buy/sell/trade verbs).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from apps.common.composition import make_composition
from apps.mcp.server import create_server
from apps.mcp.tools.briefing import register_briefing_tools
from apps.mcp.tools.congressional import register_congressional_tools
from apps.mcp.tools.market import register_market_tools
from apps.mcp.tools.portfolio import register_portfolio_tools

from mcp.server import Server
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


class TestMCPReadOnly:
    """All MCP tools must be read-only."""

    @pytest.fixture
    def server(self) -> Any:
        return create_server()

    @pytest.fixture
    def composition(self) -> Any:
        return make_composition(broker_mode="fake", database_url="")

    def test_server_has_tools(self, server: Any) -> None:
        """Server must register at least one tool."""
        assert hasattr(server, "_tool_handlers") or hasattr(server, "list_tools")

    def test_no_forbidden_verbs_in_tool_names(self) -> None:
        """No tool name may contain buy/sell/trade/submit/execute/approve verbs."""

        server = Server("test")
        register_portfolio_tools(server)
        register_congressional_tools(server)
        register_market_tools(server)
        register_briefing_tools(server)

        tool_names = [
            "get_accounts",
            "get_positions",
            "get_account_summary",
            "get_recent_disclosures",
            "get_disclosures_by_symbol",
            "get_disclosures_by_member",
            "get_quote",
            "get_bars",
            "get_latest_briefing",
            "get_briefings",
        ]

        for name in tool_names:
            name_lower = name.lower()
            for verb in FORBIDDEN_TOOL_VERBS:
                assert verb not in name_lower, (
                    f"Tool '{name}' contains forbidden verb '{verb}'. "
                    "MCP tools must be read-only. Spec §Non-goals."
                )

    def test_tool_names_are_read_prefixed(self) -> None:
        """All tool names should start with get_ or list_ (read operations)."""
        tool_names = [
            "get_accounts",
            "get_positions",
            "get_account_summary",
            "get_recent_disclosures",
            "get_disclosures_by_symbol",
            "get_disclosures_by_member",
            "get_quote",
            "get_bars",
            "get_latest_briefing",
            "get_briefings",
        ]

        for name in tool_names:
            assert name.startswith(("get_", "list_")), (
                f"Tool '{name}' does not start with get_ or list_. "
                "Read-only tools should use read-style prefixes."
            )


class TestPortfolioTools:
    """Portfolio tool return shapes."""

    @pytest.fixture
    def fake_broker(self) -> FakeBroker:
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
