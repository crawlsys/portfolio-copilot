"""Briefing routes — daily AI summaries of Congressional activity + portfolio."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apps.common.settings import get_settings
from trading.adapters.persistence.models import BriefingRow

router = APIRouter()


def _get_sync_session(request: Request) -> Any:

    comp = request.app.state.composition
    if comp.engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DATABASE_URL not configured.",
        )

    settings = get_settings()
    sync_url = settings.database_url
    return Session(create_engine(sync_url))


@router.get("")
def list_briefings(request: Request, limit: int = 30) -> list[dict[str, Any]]:
    """List recent briefings, newest first."""
    session = _get_sync_session(request)
    try:
        rows = (
            session.execute(
                select(BriefingRow).order_by(BriefingRow.briefing_date.desc()).limit(limit)
            )
            .scalars()
            .all()
        )
        return [_briefing_to_dict(r) for r in rows]
    finally:
        session.close()


@router.get("/latest")
def get_latest_briefing(request: Request) -> dict[str, Any]:
    """Get the most recent briefing."""
    session = _get_sync_session(request)
    try:
        row = session.scalar(
            select(BriefingRow).order_by(BriefingRow.briefing_date.desc()).limit(1)
        )
        if row is None:
            raise HTTPException(404, "No briefings found. Generate one first.")
        return _briefing_to_dict(row)
    finally:
        session.close()


@router.get("/{briefing_id}")
def get_briefing(request: Request, briefing_id: str) -> dict[str, Any]:
    """Get a single briefing by ID."""
    session = _get_sync_session(request)
    try:
        row = session.scalar(select(BriefingRow).where(BriefingRow.briefing_id == briefing_id))
        if row is None:
            raise HTTPException(404, f"Briefing not found: {briefing_id}")
        return _briefing_to_dict(row)
    finally:
        session.close()


def _briefing_to_dict(row: BriefingRow) -> dict[str, Any]:
    return {
        "briefingId": row.briefing_id,
        "briefingDate": row.briefing_date.date().isoformat()
        if hasattr(row.briefing_date, "date")
        else str(row.briefing_date),
        "periodStart": row.period_start.isoformat(),
        "periodEnd": row.period_end.isoformat(),
        "summaryMarkdown": row.summary_markdown,
        "pushExcerpt": row.push_excerpt,
        "referencedDisclosureIds": row.referenced_disclosure_ids,
        "generatedAt": row.generated_at.isoformat(),
    }
