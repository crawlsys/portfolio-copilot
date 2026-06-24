"""Digest routes — the daily frontier-model report (latest, by-date, archive)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apps.common.settings import get_settings
from trading.adapters.persistence.models import DigestRow

router = APIRouter()


def _md_to_html(md: str) -> str:
    """Render the digest markdown to HTML server-side (GFM tables + lists), so
    the frontend can drop it into a styled container without a markdown lib."""
    import markdown  # noqa: PLC0415

    return markdown.markdown(md, extensions=["tables", "sane_lists", "fenced_code"])


def _session(request: Request) -> Session:
    comp = request.app.state.composition
    if comp.engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DATABASE_URL not configured.",
        )
    return Session(create_engine(get_settings().database_url))


def _to_dict(row: DigestRow) -> dict[str, Any]:
    return {
        "digestId": row.digest_id,
        "digestDate": row.digest_date.date().isoformat(),
        "summaryMarkdown": row.summary_markdown,
        "summaryHtml": _md_to_html(row.summary_markdown),
        "pushExcerpt": row.push_excerpt,
        "model": row.model,
        "netLiquidation": row.net_liquidation,
        "cashToDeploy": row.cash_to_deploy,
        "disclosuresCount": row.disclosures_count,
        "generatedAt": row.generated_at.isoformat(),
    }


@router.get("/latest")
def get_latest_digest(request: Request) -> dict[str, Any]:
    """The most recent digest."""
    session = _session(request)
    try:
        row = session.scalar(
            select(DigestRow).order_by(DigestRow.generated_at.desc()).limit(1)
        )
        if row is None:
            raise HTTPException(404, "No digests yet. Generate one first.")
        return _to_dict(row)
    finally:
        session.close()


@router.get("/dates")
def list_digest_dates(request: Request, limit: int = 60) -> list[str]:
    """Distinct digest dates, newest first — for the archive picker."""
    session = _session(request)
    try:
        rows = session.execute(
            select(DigestRow.digest_date).order_by(DigestRow.digest_date.desc()).limit(limit)
        ).all()
        seen: list[str] = []
        for (d,) in rows:
            iso = d.date().isoformat()
            if iso not in seen:
                seen.append(iso)
        return seen
    finally:
        session.close()


@router.get("/{digest_date}")
def get_digest_for_date(request: Request, digest_date: str) -> dict[str, Any]:
    """The latest digest generated for a given YYYY-MM-DD."""
    try:
        d = date.fromisoformat(digest_date)
    except ValueError as exc:
        raise HTTPException(400, "digest_date must be YYYY-MM-DD") from exc
    session = _session(request)
    try:
        start = datetime.combine(d, datetime.min.time())
        row = session.scalar(
            select(DigestRow)
            .where(DigestRow.digest_date >= start)
            .where(DigestRow.digest_date < start + timedelta(days=1))
            .order_by(DigestRow.generated_at.desc())
            .limit(1)
        )
        if row is None:
            raise HTTPException(404, f"No digest for {digest_date}.")
        return _to_dict(row)
    finally:
        session.close()
