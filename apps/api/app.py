"""FastAPI app factory.

Single entrypoint for `uvicorn apps.api.app:create_app --factory`.
Composition is built lazily on first request to allow tests to override
dependencies via FastAPI's Depends() injection.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from apps.api.routes.audit import router as audit_router
from apps.api.routes.briefings import router as briefings_router
from apps.api.routes.congressional import router as congressional_router
from apps.api.routes.health import router as health_router
from apps.api.routes.portfolio import router as portfolio_router
from apps.common.composition import make_composition
from apps.common.settings import Settings, get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build composition on startup; tear down on shutdown."""
    settings: Settings = get_settings()
    comp = make_composition(
        broker_mode=settings.broker_mode,
        database_url=settings.database_url,
        massive_api_key=settings.massive_api_key,
        s3_endpoint_url=settings.s3_endpoint_url,
        s3_bucket=settings.s3_bucket,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        push_provider=settings.push_provider,
        ntfy_server_url=settings.ntfy_server_url,
        ntfy_topic=settings.ntfy_topic,
        ntfy_auth_token=settings.ntfy_auth_token,
    )
    app.state.composition = comp
    yield
    if comp.engine is not None:
        await comp.engine.dispose()


def create_app() -> FastAPI:
    """Build the FastAPI app. Called by uvicorn --factory and tests."""
    app = FastAPI(
        title="tracker",
        description=(
            "Personal portfolio + Congressional research tool. "
            "No live trade execution (see spec §Non-goals)."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # Routers imported at module top to avoid lazy imports.
    app.include_router(health_router)
    app.include_router(portfolio_router, prefix="/portfolio", tags=["portfolio"])
    app.include_router(audit_router, prefix="/audit", tags=["audit"])
    app.include_router(congressional_router, prefix="/congressional", tags=["congressional"])
    app.include_router(briefings_router, prefix="/briefings", tags=["briefings"])

    return app


__all__ = ["create_app", "lifespan"]
