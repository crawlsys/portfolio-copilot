"""Briefing read-only tools — daily AI briefings.

Briefings are retrieved from the database via the persistence layer.
For now, returns empty results when no DB is configured (test mode).
"""

from __future__ import annotations

from datetime import UTC, datetime

from mcp.types import TextContent, Tool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.common.composition import Composition
from mcp.server import Server
from trading.adapters.persistence.models import BriefingRow
from trading.domain import Briefing, BriefingId, SignalId


def _row_to_briefing(row: BriefingRow) -> Briefing:
    return Briefing(
        briefing_id=BriefingId(row.briefing_id),
        briefing_date=row.briefing_date.date(),
        period_start=row.period_start,
        period_end=row.period_end,
        summary_markdown=row.summary_markdown,
        push_excerpt=row.push_excerpt,
        referenced_signal_ids=tuple(SignalId(s) for s in row.referenced_signal_ids),
        referenced_disclosure_ids=tuple(row.referenced_disclosure_ids),
        body_blob_key=row.body_blob_key,
        generated_at=row.generated_at,
    )


def _briefing_to_dict(b: Briefing) -> dict[str, object]:
    return {
        "briefing_id": b.briefing_id,
        "briefing_date": b.briefing_date.isoformat(),
        "period_start": b.period_start.isoformat(),
        "period_end": b.period_end.isoformat(),
        "summary_markdown": b.summary_markdown,
        "push_excerpt": b.push_excerpt,
        "referenced_signal_ids": list(b.referenced_signal_ids),
        "referenced_disclosure_ids": list(b.referenced_disclosure_ids),
        "generated_at": b.generated_at.isoformat() if b.generated_at else None,
    }


def register_briefing_tools(server: Server) -> None:
    """Register briefing read-only tools."""

    @server.list_tools()
    async def list_briefing_tools() -> list[Tool]:
        return [
            Tool(
                name="get_latest_briefing",
                description="Get the most recent daily AI briefing.",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
            Tool(
                name="get_briefings",
                description="Get briefing history since a specific date.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "since": {
                            "type": "string",
                            "description": "ISO date string (YYYY-MM-DD) to fetch briefings since.",
                        },
                    },
                    "required": ["since"],
                },
            ),
        ]

    @server.call_tool()
    async def call_briefing_tool(name: str, arguments: dict[str, object]) -> list[TextContent]:
        comp: Composition = server.state  # type: ignore[attr-defined]

        if comp.engine is None:
            return [
                TextContent(
                    type="text",
                    text=str({"error": "Database not configured. No briefings available."}),
                )
            ]

        if name == "get_latest_briefing":
            async with AsyncSession(comp.engine, expire_on_commit=False) as session:
                stmt = select(BriefingRow).order_by(BriefingRow.briefing_date.desc()).limit(1)
                query_result = await session.execute(stmt)
                row = query_result.scalar_one_or_none()
                if row is None:
                    return [TextContent(type="text", text=str({"briefing": None}))]
                briefing = _row_to_briefing(row)
                return [TextContent(type="text", text=str(_briefing_to_dict(briefing)))]

        if name == "get_briefings":
            since_str = str(arguments.get("since", ""))
            try:
                since_date = datetime.fromisoformat(since_str).replace(tzinfo=UTC)
            except ValueError:
                return [
                    TextContent(
                        type="text",
                        text=str({"error": f"Invalid date format: {since_str}"}),
                    )
                ]

            async with AsyncSession(comp.engine, expire_on_commit=False) as session:
                stmt = (
                    select(BriefingRow)
                    .where(BriefingRow.briefing_date >= since_date)
                    .order_by(BriefingRow.briefing_date.desc())
                )
                query_result = await session.execute(stmt)
                rows = query_result.scalars().all()
                briefings = [_briefing_to_dict(_row_to_briefing(r)) for r in rows]
                return [TextContent(type="text", text=str({"briefings": briefings}))]

        return [TextContent(type="text", text=f"Unknown tool: {name}")]
