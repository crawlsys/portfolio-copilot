"""Market data read-only tools — quotes and bars.

All tools query through BrokerPort for quotes. Bars are not yet
implemented in FakeBroker (returns empty for now).
"""

from __future__ import annotations

from mcp.types import TextContent, Tool

from apps.common.composition import Composition
from mcp.server import Server
from trading.domain import Bar, Quote, Symbol


def _quote_to_dict(q: Quote) -> dict[str, object]:
    return {
        "symbol": q.symbol.ticker,
        "bid": str(q.bid),
        "ask": str(q.ask),
        "last": str(q.last),
        "mid": str(q.mid),
        "spread": str(q.spread),
        "volume": q.volume,
        "timestamp": q.timestamp.isoformat(),
    }


def _bar_to_dict(b: Bar) -> dict[str, object]:
    return {
        "symbol": b.symbol.ticker,
        "open": str(b.open),
        "high": str(b.high),
        "low": str(b.low),
        "close": str(b.close),
        "volume": b.volume,
        "timeframe": b.timeframe,
        "opened_at": b.opened_at.isoformat(),
        "closed_at": b.closed_at.isoformat(),
        "vwap": str(b.vwap) if b.vwap else None,
    }


def register_market_tools(server: Server) -> None:
    """Register market data read-only tools."""

    @server.list_tools()
    async def list_market_tools() -> list[Tool]:
        return [
            Tool(
                name="get_quote",
                description="Get the current quote for a stock symbol.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Stock ticker symbol (e.g., AAPL, NVDA).",
                        },
                    },
                    "required": ["symbol"],
                },
            ),
            Tool(
                name="get_bars",
                description="Get historical OHLCV bars for a stock symbol.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Stock ticker symbol (e.g., AAPL, NVDA).",
                        },
                        "timeframe": {
                            "type": "string",
                            "description": "Bar timeframe (1m, 5m, 1h, 1d).",
                            "default": "1d",
                        },
                        "days": {
                            "type": "integer",
                            "description": "Number of days of history to fetch.",
                            "default": 30,
                        },
                    },
                    "required": ["symbol"],
                },
            ),
        ]

    @server.call_tool()
    async def call_market_tool(name: str, arguments: dict[str, object]) -> list[TextContent]:
        comp: Composition = server.state  # type: ignore[attr-defined]

        if name == "get_quote":
            symbol_str = str(arguments.get("symbol", ""))
            symbol = Symbol(symbol_str.upper())
            try:
                quote = await comp.broker.get_quote(symbol)
                data: dict[str, object] = _quote_to_dict(quote)
            except KeyError:
                data = {"error": f"No quote available for {symbol_str}"}
            return [TextContent(type="text", text=str(data))]

        if name == "get_bars":
            symbol_str = str(arguments.get("symbol", ""))
            bars_data: dict[str, object] = {
                "symbol": symbol_str,
                "bars": [],
                "note": "Historical bars not yet implemented in FakeBroker.",
            }
            return [TextContent(type="text", text=str(bars_data))]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]
