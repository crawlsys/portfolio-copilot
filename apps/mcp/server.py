"""MCP server for tracker — exposes read-only tools to AI clients.

Per spec: no live trade execution. All tools are read-only queries against
the broker adapter. The scope guard in tests/e2e/test_read_only_surface.py
enforces this at CI time.

Transport (MCP_TRANSPORT env, default stdio):
- stdio: dev / local agents (python -m apps.mcp.server)
- http:  streamable HTTP on MCP_PORT (default 8765) at /mcp — the in-cluster
  Deployment (infra/k8s/base/mcp.yaml). ClusterIP only, no Ingress: the MCP
  protocol carries no auth here and the tools serve live brokerage data.

Composition is wired from apps.common.settings (same as the API and worker),
NOT raw env defaults — an MCP pod with the standard secret envFrom sees the
same broker/DB/market-data the rest of the system sees.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator

from mcp.server.stdio import stdio_server

from apps.common.composition import Composition, make_composition
from apps.common.settings import get_settings
from apps.mcp.tools import register_all_tools
from mcp.server import Server

_LOGGER = logging.getLogger(__name__)

DEFAULT_HTTP_PORT = 8765


def _make_composition() -> Composition:
    """Wire the Composition from Settings, mirroring the worker jobs."""
    settings = get_settings()
    return make_composition(
        broker_mode=settings.broker_mode,
        database_url=settings.database_url,
        massive_api_key=settings.massive_api_key,
        schwab_client_id=settings.schwab_client_id,
        schwab_client_secret=settings.schwab_client_secret,
        schwab_redirect_uri=settings.schwab_redirect_uri,
        schwab_token_path=settings.schwab_token_path,
    )


def create_server(comp: Composition | None = None) -> Server:
    """Create the MCP server with all read-only tools and wired state."""
    server = Server("tracker")
    register_all_tools(server)
    server.state = comp if comp is not None else _make_composition()  # type: ignore[attr-defined]
    return server


async def run_stdio() -> None:
    """Run the MCP server over stdio transport (dev / local agents)."""
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        _LOGGER.info("Tracker MCP server running on stdio")
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


async def run_http(port: int) -> None:
    """Run the MCP server over streamable HTTP (in-cluster Deployment)."""
    import uvicorn  # noqa: PLC0415 — HTTP-only deps, lazy so stdio stays lean
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager  # noqa: PLC0415
    from starlette.applications import Starlette  # noqa: PLC0415
    from starlette.routing import Mount  # noqa: PLC0415

    server = create_server()
    # Stateless: each request self-contained; no session resumption needed for
    # read-only tools, and it keeps the pod restartable without client errors.
    session_manager = StreamableHTTPSessionManager(app=server, stateless=True)

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            _LOGGER.info("Tracker MCP server running on http://0.0.0.0:%d/mcp", port)
            yield

    app = Starlette(
        routes=[Mount("/mcp", app=session_manager.handle_request)],
        lifespan=lifespan,
    )
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")  # noqa: S104
    await uvicorn.Server(config).serve()


def main() -> None:
    """Entry point — transport selected by MCP_TRANSPORT (stdio | http)."""
    logging.basicConfig(level=logging.INFO)
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    settings = get_settings()
    _LOGGER.info(
        "Tracker MCP server starting (transport=%s, broker_mode=%s)",
        transport,
        settings.broker_mode,
    )
    if transport == "http":
        port = int(os.getenv("MCP_PORT", str(DEFAULT_HTTP_PORT)))
        asyncio.run(run_http(port))
    else:
        asyncio.run(run_stdio())


if __name__ == "__main__":
    main()
