"""Portfolio read-only tools — accounts, positions, summaries.

All tools query through BrokerPort, never directly to DB.

Module contract (see apps/mcp/tools/__init__.py): expose ``TOOLS`` and
``handle()``. The low-level MCP Server keeps ONE handler per request type,
so modules must never call @server.list_tools()/@server.call_tool()
themselves — the aggregator in __init__.py owns the single registration.
"""

from __future__ import annotations

from mcp.types import TextContent, Tool

from apps.common.composition import Composition
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


TOOLS: list[Tool] = [
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

_TOOL_NAMES = frozenset(t.name for t in TOOLS)


async def handle(
    name: str, arguments: dict[str, object], comp: Composition
) -> list[TextContent] | None:
    """Handle a portfolio tool call; None if *name* is not ours."""
    if name not in _TOOL_NAMES:
        return None

    if name == "get_accounts":
        accounts = await comp.broker.get_accounts()
        accounts_data = [_account_to_dict(a) for a in accounts]
        return [TextContent(type="text", text=str(accounts_data))]

    if name == "get_positions":
        account_id = str(arguments.get("account_id", ""))
        positions = await comp.broker.get_positions(account_id)
        positions_data = [_position_to_dict(p) for p in positions]
        return [TextContent(type="text", text=str(positions_data))]

    # get_account_summary
    account_id = str(arguments.get("account_id", ""))
    snapshot = await comp.broker.get_account(account_id)
    summary_data = _account_snapshot_to_dict(snapshot)
    return [TextContent(type="text", text=str(summary_data))]
