"""MCP tool registry — ALL tools are READ-ONLY.

The scope guard in tests/e2e/test_read_only_surface.py asserts that no tool
module in this directory has a name suggesting trading (orders, trades,
approvals, execution). This is enforced at CI.

Tool naming: lowercase, underscores, descriptive. All tools get_ or list_.
Never buy_, sell_, trade_, submit_, execute_, approve_.
"""

from __future__ import annotations

from apps.mcp.tools.briefing import register_briefing_tools
from apps.mcp.tools.congressional import register_congressional_tools
from apps.mcp.tools.market import register_market_tools
from apps.mcp.tools.portfolio import register_portfolio_tools
from mcp.server import Server


def register_all_tools(server: Server) -> None:
    """Register all read-only tools on the MCP server."""
    register_portfolio_tools(server)
    register_congressional_tools(server)
    register_market_tools(server)
    register_briefing_tools(server)


__all__ = ["register_all_tools"]
