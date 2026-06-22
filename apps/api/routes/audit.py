"""Audit query routes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import text

from apps.common.composition import Composition, session_factory

router = APIRouter()

AUDIT_CHAIN_SQL = text(
    """
    SELECT
        audit_id,
        event_type,
        actor,
        action,
        subject_type,
        subject_id,
        occurred_at,
        correlation_id,
        metadata
    FROM audit_log
    WHERE correlation_id = :correlation_id
    ORDER BY occurred_at ASC, id ASC
    """
)

AUDIT_SUBJECT_SQL = text(
    """
    SELECT
        audit_id,
        event_type,
        actor,
        action,
        subject_type,
        subject_id,
        occurred_at,
        correlation_id,
        metadata
    FROM audit_log
    WHERE subject_type = :subject_type AND subject_id = :subject_id
    ORDER BY occurred_at ASC, id ASC
    """
)


class AuditMappings(Protocol):
    def all(self) -> Sequence[Mapping[str, object]]: ...


class AuditResult(Protocol):
    def mappings(self) -> AuditMappings: ...


class AuditSession(Protocol):
    async def execute(self, statement: object, params: dict[str, object]) -> AuditResult: ...


@router.get("/chain/{correlation_id}")
async def get_audit_chain(correlation_id: str, request: Request) -> dict[str, object]:
    comp: Composition = request.app.state.composition
    if comp.engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DATABASE_URL not configured; audit queries require persistence.",
        )

    async with session_factory(comp) as session:
        rows = await _fetch_audit_records(
            session,
            statement=AUDIT_CHAIN_SQL,
            params={"correlation_id": correlation_id},
        )
    return {"correlation_id": correlation_id, "events": rows}


@router.get("/subject/{type}/{id}")
async def get_audit_subject(type: str, id: str, request: Request) -> dict[str, object]:  # noqa: A002
    comp: Composition = request.app.state.composition
    if comp.engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DATABASE_URL not configured; audit queries require persistence.",
        )

    async with session_factory(comp) as session:
        rows = await _fetch_audit_records(
            session,
            statement=AUDIT_SUBJECT_SQL,
            params={"subject_type": type, "subject_id": id},
        )
    return {"subject_type": type, "subject_id": id, "events": rows}


async def _fetch_audit_records(
    session: AuditSession,
    *,
    statement: object,
    params: dict[str, object],
) -> list[dict[str, object]]:
    result = await session.execute(statement, params)
    return [_audit_row_to_dict(row) for row in result.mappings().all()]


def _audit_row_to_dict(row: Mapping[str, object]) -> dict[str, object]:
    occurred_at = row["occurred_at"]
    timestamp = occurred_at.isoformat() if isinstance(occurred_at, datetime) else str(occurred_at)

    metadata = row["metadata"]
    return {
        "audit_id": row["audit_id"],
        "event_type": row["event_type"],
        "actor": row["actor"],
        "action": row["action"],
        "subject_type": row["subject_type"],
        "subject_id": row["subject_id"],
        "timestamp": timestamp,
        "correlation_id": row["correlation_id"],
        "metadata": metadata if isinstance(metadata, dict) else {},
    }


__all__ = ["router"]
