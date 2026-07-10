"""Congressional disclosure read-only tools.

Exposes trade disclosures from the QuiverClient adapter.
All tools are read-only — no writes, no approvals.

Module contract (see apps/mcp/tools/__init__.py): expose ``TOOLS`` and
``handle()``; never register handlers on the Server directly.
"""

from __future__ import annotations

import os

from mcp.types import TextContent, Tool

from apps.common.composition import Composition
from trading.adapters.quiver.client import QuiverClient
from trading.domain import Symbol, TradeDisclosure


def _disclosure_to_dict(d: TradeDisclosure) -> dict[str, object]:
    return {
        "filing_id": d.filing_id,
        "member_id": d.member_id,
        "member_name": d.member_name,
        "symbol": d.symbol.ticker if d.symbol else None,
        "asset_description": d.asset_description,
        "transaction_type": d.transaction_type.name,
        "transaction_date": d.transaction_date.isoformat(),
        "disclosure_date": d.disclosure_date.isoformat(),
        "amount_range_low": d.amount_range_low,
        "amount_range_high": d.amount_range_high,
        "lag_days": d.lag_days,
    }


def _get_quiver_client() -> QuiverClient:
    api_key = os.getenv("QUIVER_API_KEY", "")
    return QuiverClient(api_key=api_key)


TOOLS: list[Tool] = [
    Tool(
        name="get_recent_disclosures",
        description="Get recent congressional trade disclosures.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of disclosures to return.",
                    "default": 10,
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="get_disclosures_by_symbol",
        description="Get congressional trade disclosures for a specific stock ticker.",
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
        name="get_disclosures_by_member",
        description="Get congressional trade disclosures by a specific member of Congress.",
        inputSchema={
            "type": "object",
            "properties": {
                "member_name": {
                    "type": "string",
                    "description": "Name of the Congress member.",
                },
            },
            "required": ["member_name"],
        },
    ),
]

_TOOL_NAMES = frozenset(t.name for t in TOOLS)


async def handle(
    name: str, arguments: dict[str, object], comp: Composition
) -> list[TextContent] | None:
    """Handle a congressional tool call; None if *name* is not ours.

    *comp* is unused — disclosures come from QuiverClient directly — but the
    signature matches the module contract.
    """
    if name not in _TOOL_NAMES:
        return None

    client = _get_quiver_client()

    if name == "get_recent_disclosures":
        limit_val = arguments.get("limit", 10)
        limit = int(str(limit_val)) if limit_val is not None else 10
        disclosures = await client.get_recent_disclosures(limit=limit)
        data = [_disclosure_to_dict(d) for d in disclosures]
        return [TextContent(type="text", text=str(data))]

    if name == "get_disclosures_by_symbol":
        symbol_str = str(arguments.get("symbol", ""))
        symbol = Symbol(symbol_str.upper())
        disclosures = await client.get_disclosures_by_symbol(symbol)
        data = [_disclosure_to_dict(d) for d in disclosures]
        return [TextContent(type="text", text=str(data))]

    # get_disclosures_by_member
    member_name = str(arguments.get("member_name", ""))
    disclosures = await client.get_disclosures_by_member(member_name)
    data = [_disclosure_to_dict(d) for d in disclosures]
    return [TextContent(type="text", text=str(data))]
