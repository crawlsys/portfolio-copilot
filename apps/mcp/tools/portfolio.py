"""Portfolio read-only tools — accounts, positions, summaries.

All tools query through BrokerPort, never directly to DB.
"""

from __future__ import annotations

from mcp.types import TextContent, Tool

from apps.common.composition import Composition
from mcp.server import Server
from trading.domain import Account, BrokerAccount, Position


def _account_to_dict(acct: BrokerAccount) -> dict[str, object]:
    return {
        "account_id": acct.account_id,
        "nickname": acct.nickname,
        "masked_schwab_id": acct.masked_schwab_id,
        "account_type": acct.account_type.name,
        "margin_enabled": acct.margin_enabled,
    }


def _position_to_dict(pos: Position) -> dict[str, object]:
    return {
        "account_id": pos.account_id,
        "symbol": pos.symbol.ticker,
        "quantity": str(pos.quantity),
        "average_cost": str(pos.average_cost.amount),
        "average_cost_currency": pos.average_cost.currency,
        "market_value": str(pos.market_value.amount),
        "unrealized_pnl": str(pos.unrealized_pnl.amount),
        "is_long": pos.is_long,
        "as_of": pos.as_of.isoformat(),
    }


def _account_snapshot_to_dict(snapshot: Account) -> dict[str, object]:
    return {
        "account_id": snapshot.account_id,
        "cash": str(snapshot.cash.amount),
        "cash_currency": snapshot.cash.currency,
        "market_value": str(snapshot.market_value.amount),
        "net_liquidation": str(snapshot.net_liquidation.amount),
        "buying_power": str(snapshot.buying_power.amount),
        "positions": [_position_to_dict(p) for p in snapshot.positions],
        "as_of": snapshot.as_of.isoformat() if snapshot.as_of else None,
    }


def register_portfolio_tools(server: Server) -> None:
    """Register portfolio read-only tools."""

    @server.list_tools()
    async def list_portfolio_tools() -> list[Tool]:
        return [
            Tool(
                name="get_accounts",
                description="List all linked broker accounts with type and margin metadata.",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
            Tool(
                name="get_positions",
                description="Get all positions for a specific account.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "account_id": {
                            "type": "string",
                            "description": "The broker account ID.",
                        },
                    },
                    "required": ["account_id"],
                },
            ),
            Tool(
                name="get_account_summary",
                description="Get a full account snapshot including balances and all positions.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "account_id": {
                            "type": "string",
                            "description": "The broker account ID.",
                        },
                    },
                    "required": ["account_id"],
                },
            ),
        ]

    @server.call_tool()
    async def call_portfolio_tool(name: str, arguments: dict[str, object]) -> list[TextContent]:
        comp: Composition = server.state  # type: ignore[attr-defined]

        if name == "get_accounts":
            accounts = await comp.broker.get_accounts()
            accounts_data = [_account_to_dict(a) for a in accounts]
            return [TextContent(type="text", text=str(accounts_data))]

        if name == "get_positions":
            account_id = str(arguments.get("account_id", ""))
            positions = await comp.broker.get_positions(account_id)
            positions_data = [_position_to_dict(p) for p in positions]
            return [TextContent(type="text", text=str(positions_data))]

        if name == "get_account_summary":
            account_id = str(arguments.get("account_id", ""))
            snapshot = await comp.broker.get_account(account_id)
            summary_data = _account_snapshot_to_dict(snapshot)
            return [TextContent(type="text", text=str(summary_data))]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]
