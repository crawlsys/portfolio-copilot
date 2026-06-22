"""Scheduled job: generate the daily briefing.

Runs once per day (default: 7 AM local) after the congressional ingest job
has pulled new disclosures. Calls the GenerateBriefing use case.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from apps.common.settings import get_settings
from trading.application.common.clock import SystemClock
from trading.application.common.unit_of_work import UnitOfWork
from trading.domain import Severity
from trading.application.market_data.refresh_quotes import MarketDataPort, NoMarketData
from trading.application.signals.generate_briefing import (
    GenerateBriefingCommand,
    execute,
)

_log = logging.getLogger(__name__)


async def run_briefing() -> None:
    """Generate today's (or latest) daily briefing."""
    settings = get_settings()

    if not settings.database_url:
        _log.warning("DATABASE_URL not set — skipping briefing generation")
        return

    engine = create_async_engine(
        settings.database_url.replace("+psycopg", "+psycopg_async"),
        poolclass=NullPool,
    )
    try:
        # Market data: use Massive if key present, else NoMarketData
        market_data: MarketDataPort = NoMarketData()
        if settings.massive_api_key:
            from trading.adapters.massive.client import MassiveClient  # noqa: PLC0415

            market_data = MassiveClient(api_key=settings.massive_api_key)

        clock = SystemClock()
        async with AsyncSession(engine, expire_on_commit=False) as session:
            uow = UnitOfWork(
                session=session,
                clock=clock,
                correlation_id=uuid4(),
            )
            async with uow:
                result = await execute(
                    GenerateBriefingCommand(
                        correlation_id=uow.correlation_id,
                        actor="scheduler",
                    ),
                    uow=uow,
                    market_data=market_data,
                    llm_provider=settings.llm_provider,
                    llm_api_key=settings.llm_api_key,
                    llm_model=settings.llm_model,
                )

        _log.info(
            "briefing generated: %s — %d disclosures, %d overlaps, regime=%s, by=%s",
            result.briefing_id,
            result.disclosures_count,
            result.portfolio_overlaps,
            result.market_regime,
            "llm" if settings.llm_api_key else "template",
        )
        _log.info("push excerpt: %s", result.push_excerpt)

        # Push the briefing excerpt via Pushover (if configured)
        if settings.push_provider == "pushover" and settings.pushover_api_token:
            from trading.adapters.notifications.pushover import PushoverNotifier  # noqa: PLC0415

            notifier = PushoverNotifier(
                api_token=settings.pushover_api_token,
                user_key=settings.pushover_user_key,
            )
            overlap_note = (
                f" {result.portfolio_overlaps} overlap(s) with your portfolio."
                if result.portfolio_overlaps
                else ""
            )
            await notifier.send(
                title=f"📊 Daily Briefing — {result.briefing_date.isoformat()}",
                body=f"{result.disclosures_count} new disclosure(s).{overlap_note} "
                f"Regime: {result.market_regime}.\n\n{result.push_excerpt}",
                severity=Severity.INFO,
                tags=["briefing", "congress"],
                click_url=None,  # TODO: dashboard URL when deployed
            )
            await notifier.aclose()
            _log.info("briefing pushed via Pushover")
    finally:
        await engine.dispose()


def run_briefing_sync() -> None:
    """Sync wrapper for APScheduler."""
    asyncio.run(run_briefing())
