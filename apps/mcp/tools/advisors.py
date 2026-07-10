"""Advisor council read-only tools — persona analysts' views on held tickers.

Views are formed by the advisor_views worker job (persona LLM over a
point-in-time fundamentals snapshot) and persisted with their full prompt +
response audit trail. These tools only READ that table — external agents get
the council's takes, never any trading capability.

Module contract (see apps/mcp/tools/__init__.py): expose ``TOOLS`` and
``handle()``; never register handlers on the Server directly.
"""

from __future__ import annotations

from mcp.types import TextContent, Tool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.common.composition import Composition
from trading.adapters.persistence.models import AdvisorViewRow


def _view_to_dict(row: AdvisorViewRow) -> dict[str, object]:
    return {
        "advisor": row.advisor,
        "model": row.model,
        "ticker": row.ticker,
        "as_of": row.as_of.isoformat(),
        "stance": row.stance,
        "confidence": float(row.confidence),
        "reasoning": row.reasoning,
        "abstained": row.abstained,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


TOOLS: list[Tool] = [
    Tool(
        name="list_advisors",
        description=(
            "List the advisor personas whose views are available "
            "(e.g. 'buffett' — fundamentals-driven value analyst)."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="get_advisor_views",
        description=(
            "Get the latest advisor-council views (stance, confidence, thesis) — "
            "persona analysts reasoning over point-in-time fundamentals. "
            "Optionally filter to one ticker."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Optional stock ticker to filter (e.g., AAPL).",
                },
            },
            "required": [],
        },
    ),
]

_TOOL_NAMES = frozenset(t.name for t in TOOLS)


async def handle(
    name: str, arguments: dict[str, object], comp: Composition
) -> list[TextContent] | None:
    """Handle an advisor tool call; None if *name* is not ours."""
    if name not in _TOOL_NAMES:
        return None

    if comp.engine is None:
        return [
            TextContent(
                type="text",
                text=str({"error": "Database not configured. No advisor views available."}),
            )
        ]

    if name == "list_advisors":
        async with AsyncSession(comp.engine, expire_on_commit=False) as session:
            names_result = await session.execute(select(AdvisorViewRow.advisor).distinct())
            advisors = sorted(names_result.scalars().all())
        return [TextContent(type="text", text=str({"advisors": advisors}))]

    # get_advisor_views — latest non-abstained view per (ticker, advisor)
    ticker = str(arguments.get("ticker", "")).upper().strip()
    stmt = (
        select(AdvisorViewRow)
        .where(AdvisorViewRow.abstained.is_(False))
        .order_by(AdvisorViewRow.created_at.desc())
    )
    if ticker:
        stmt = stmt.where(AdvisorViewRow.ticker == ticker)
    async with AsyncSession(comp.engine, expire_on_commit=False) as session:
        views_result = await session.execute(stmt)
        rows = views_result.scalars().all()

    latest: dict[tuple[str, str], AdvisorViewRow] = {}
    for row in rows:
        latest.setdefault((row.ticker, row.advisor), row)
    views = [_view_to_dict(row) for _key, row in sorted(latest.items())]
    return [TextContent(type="text", text=str({"views": views}))]
