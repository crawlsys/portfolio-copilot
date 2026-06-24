"""Daily digest job: generate the frontier-model digest, persist it, and push a
Pushover summary that links to the digest page on the dashboard."""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from apps.common.settings import get_settings
from trading.application.common.clock import SystemClock
from trading.application.common.unit_of_work import UnitOfWork
from trading.application.market_data.refresh_quotes import MarketDataPort, NoMarketData
from trading.application.signals.generate_digest import GenerateDigestCommand, execute
from trading.domain import Severity

_log = logging.getLogger(__name__)


async def run_digest() -> None:
    """Generate today's digest and push a linked summary."""
    settings = get_settings()
    if not settings.database_url:
        _log.warning("DATABASE_URL not set — skipping digest generation")
        return

    engine = create_async_engine(
        settings.database_url.replace("+psycopg", "+psycopg_async"),
        poolclass=NullPool,
    )
    try:
        market_data: MarketDataPort = NoMarketData()
        if settings.massive_api_key:
            from trading.adapters.massive.client import MassiveClient  # noqa: PLC0415

            market_data = MassiveClient(api_key=settings.massive_api_key)

        async with AsyncSession(engine, expire_on_commit=False) as session:
            uow = UnitOfWork(session=session, clock=SystemClock(), correlation_id=uuid4())
            async with uow:
                result = await execute(
                    GenerateDigestCommand(correlation_id=uow.correlation_id, actor="scheduler"),
                    uow=uow,
                    market_data=market_data,
                    openrouter_api_key=settings.openrouter_api_key,
                    model=settings.digest_model,
                    cash_to_deploy=settings.digest_cash_to_deploy,
                )

        _log.info(
            "digest generated: %s — %d disclosures, by=%s, model=%s",
            result.digest_id,
            result.disclosures_count,
            result.generated_by,
            result.model,
        )
        _log.info("push excerpt: %s", result.push_excerpt)

        if settings.push_provider == "pushover" and settings.pushover_api_token:
            from trading.adapters.notifications.pushover import PushoverNotifier  # noqa: PLC0415

            notifier = PushoverNotifier(
                api_token=settings.pushover_api_token,
                user_key=settings.pushover_user_key,
            )
            await notifier.send(
                title=f"📊 Daily Digest — {result.digest_date.isoformat()}",
                body=result.push_excerpt,
                severity=Severity.INFO,
                tags=["digest"],
                click_url=settings.digest_url,
                html=False,
            )
            await notifier.aclose()
            _log.info("digest pushed via Pushover")
    finally:
        await engine.dispose()


def run_digest_sync() -> None:
    """Sync wrapper for the CronJob dispatcher."""
    asyncio.run(run_digest())
