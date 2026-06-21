"""Health endpoints — liveness + readiness.

- /health/live: process is up. Always 200 if the route responds.
- /health/ready: composition is built + (when configured) DB reachable.
"""
from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready() -> JSONResponse:
    """Ready iff composition is built. Optionally pings DB.

    For v1 this is always 200 once the app is up — we don't have a hard
    DB dependency in the hot path yet (FakeBroker works without DB).
    """
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "ok"},
    )
