"""MCP server for tracker — exposes read-only tools to AI clients.

Per spec: no live trade execution. All tools are read-only queries against
the broker adapter. The scope guard in tests/e2e/test_read_only_surface.py
enforces this at CI time.

Transport:
- Dev: stdio (mcp run python -m apps.mcp.server)
- Prod: streamable HTTP (separate k8s Deployment)
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.stdio import stdio_server

from apps.common.composition import Composition, make_composition
from apps.mcp.tools import register_all_tools
from mcp.server import Server

_LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def _make_lifespan(server: Server) -> AsyncIterator[Composition]:
    """Construct the wired Composition and yield it for tool handlers."""
    broker_mode = os.getenv("BROKER_MODE", "fake")
    database_url = os.getenv("DATABASE_URL", "")
    comp = make_composition(broker_mode=broker_mode, database_url=database_url)
    _LOGGER.info("Tracker MCP server starting (broker_mode=%s)", broker_mode)
    yield comp
    _LOGGER.info("Tracker MCP server shutting down")


def create_server() -> Server:
    """Create and configure the MCP server with all read-only tools."""
    server = Server("tracker")
    register_all_tools(server)
    return server


async def run_stdio() -> None:
    """Run the MCP server over stdio transport (dev mode)."""
    server = create_server()
    comp = make_composition(
        broker_mode=os.getenv("BROKER_MODE", "fake"),
        database_url=os.getenv("DATABASE_URL", ""),
    )
    server.state = comp  # type: ignore[attr-defined]

    async with stdio_server() as (read_stream, write_stream):
        _LOGGER.info("Tracker MCP server running on stdio")
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    """Entry point for the MCP server."""
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_stdio())


if __name__ == "__main__":
    main()
