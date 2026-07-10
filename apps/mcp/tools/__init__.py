"""MCP tool registry — ALL tools are READ-ONLY.

The scope guard in tests/e2e/test_read_only_surface.py asserts that no tool
module in this directory has a name suggesting trading (orders, trades,
approvals, execution). This is enforced at CI.

Tool naming: lowercase, underscores, descriptive. All tools get_ or list_.
Never buy_, sell_, trade_, submit_, execute_, approve_.

Registration model: the low-level ``mcp.server.Server`` keeps exactly ONE
handler per request type — a second ``@server.list_tools()`` registration
silently REPLACES the first (this shipped as a bug: only the last-registered
module's tools were visible). Therefore each tool module exposes a passive
``TOOLS: list[Tool]`` plus ``async handle(name, arguments, comp)`` returning
``None`` for names it doesn't own, and this package registers a single
aggregated list_tools/call_tool pair over all modules.
"""

from __future__ import annotations

from mcp.types import TextContent, Tool

from apps.common.composition import Composition
from apps.mcp.tools import briefing, congressional, market, portfolio
from mcp.server import Server

_MODULES = (portfolio, congressional, market, briefing)


def all_tools() -> list[Tool]:
    """Every read-only tool across all modules, in registration order."""
    return [tool for module in _MODULES for tool in module.TOOLS]


async def dispatch(
    name: str, arguments: dict[str, object], comp: Composition
) -> list[TextContent]:
    """Route a tool call to the owning module."""
    for module in _MODULES:
        result: list[TextContent] | None = await module.handle(name, arguments, comp)
        if result is not None:
            return result
    return [TextContent(type="text", text=f"Unknown tool: {name}")]


def register_all_tools(server: Server) -> None:
    """Register the single aggregated list_tools/call_tool pair."""

    @server.list_tools()
    async def _list_all_tools() -> list[Tool]:
        return all_tools()

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, object]) -> list[TextContent]:
        comp: Composition = server.state  # type: ignore[attr-defined]
        return await dispatch(name, arguments, comp)


__all__ = ["all_tools", "dispatch", "register_all_tools"]
