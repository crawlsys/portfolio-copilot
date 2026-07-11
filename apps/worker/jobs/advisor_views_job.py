"""Advisor council job: run persona analysts over every held equity.

For each distinct EQUITY ticker in positions, build the point-in-time
fundamentals snapshot (as of today) and ask each advisor for a view. The
advisor_views table is cache + audit trail: an unchanged snapshot_hash means
the LLM is never re-paid for the same reasoning.

Failure contract:
- per-ticker isolation: one ticker's data failure logs and continues;
- LLM/parse failures abstain (persisted with abstained=true);
- missing config (DB / Massive / LLM key) skips the whole run with a log.

Scheduled as a k8s CronJob before the daily digest so the digest's
"Advisor Council" section sees fresh views.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from apps.common.settings import get_settings
from trading.adapters.edgar import EDGARClient, EDGARError
from trading.adapters.massive.client import MassiveClient
from trading.adapters.massive.exceptions import MassiveError
from trading.adapters.persistence.models import AdvisorViewRow, PositionRow
from trading.application.advisors import (
    ADVISOR_REGISTRY,
    AdvisorView,
    InsufficientDataError,
    OpenAICompatLLM,
    build_snapshot,
)

_log = logging.getLogger(__name__)


async def run_advisor_views() -> None:
    """Form advisor views for all held equities (cached by snapshot hash)."""
    settings = get_settings()
    missing = [
        name
        for name, value in (
            ("DATABASE_URL", settings.database_url),
            ("FUNDAMENTALS_CONFIG", _fundamentals_config(settings)),
            ("LLM_API_KEY", settings.llm_api_key),
        )
        if not value
    ]
    if missing:
        _log.warning("advisor views skipped — missing config: %s", ", ".join(missing))
        return

    engine = create_async_engine(
        settings.database_url.replace("+psycopg", "+psycopg_async"),
        poolclass=NullPool,
    )
    llm = OpenAICompatLLM(
        model=settings.advisor_model,
        api_key=settings.llm_api_key,
        base_url=settings.litellm_base_url,
    )
    advisors = [cls(llm) for cls in ADVISOR_REGISTRY.values()]
    as_of = datetime.now(UTC)

    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            result = await session.execute(
                select(PositionRow.symbol)
                .where(PositionRow.asset_class == "EQUITY", PositionRow.quantity > 0)
                .distinct()
            )
            tickers = sorted(result.scalars().all())

        if not tickers:
            _log.info("advisor views: no held equities")
            return

        _log.info(
            "advisor views: %d tickers x %d advisors (model=%s)",
            len(tickers),
            len(advisors),
            settings.advisor_model,
        )

        fresh = cached = failed = 0
        market = MassiveClient(api_key=settings.massive_api_key)
        fundamentals = (
            market
            if settings.fundamentals_source == "massive"
            else EDGARClient(settings.sec_user_agent, market_data=market if settings.massive_api_key else None)
        )
        async with market:
            for ticker in tickers:
                try:
                    snapshot = await build_snapshot(ticker, as_of.date(), fundamentals)
                except InsufficientDataError as exc:
                    _log.info("advisor views: skipping %s — %s", ticker, exc)
                    continue
                except (MassiveError, EDGARError) as exc:
                    # Per-ticker isolation: fundamentals outage for one name
                    # must not sink the whole council run.
                    _log.warning("advisor views: %s data failure — %s", ticker, exc)
                    failed += 1
                    continue

                for advisor in advisors:
                    if await _cached_view_exists(
                        engine, advisor.name, llm.model, snapshot.content_hash
                    ):
                        cached += 1
                        continue
                    view = await advisor.form_view(snapshot)
                    await _persist_view(engine, view, as_of)
                    fresh += 1

        _log.info(
            "advisor views done: %d fresh, %d cache hits, %d ticker failures",
            fresh,
            cached,
            failed,
        )
    finally:
        await engine.dispose()


async def _cached_view_exists(
    engine: AsyncEngine, advisor: str, model: str, snapshot_hash: str
) -> bool:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        result = await session.execute(
            select(AdvisorViewRow.id).where(
                AdvisorViewRow.advisor == advisor,
                AdvisorViewRow.model == model,
                AdvisorViewRow.snapshot_hash == snapshot_hash,
            )
        )
        return result.scalar_one_or_none() is not None


async def _persist_view(engine: AsyncEngine, view: AdvisorView, as_of: datetime) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(
            AdvisorViewRow(
                advisor=view.advisor,
                model=view.model,
                ticker=view.ticker,
                as_of=as_of,
                snapshot_hash=view.snapshot_hash,
                stance=view.stance,
                confidence=Decimal(str(view.confidence)),
                reasoning=view.reasoning,
                abstained=view.abstained,
                abstain_reason=view.abstain_reason,
                system_prompt=view.system_prompt,
                user_prompt=view.user_prompt,
                raw_response=view.raw_response,
            )
        )
        await session.commit()


def run_advisor_views_sync() -> None:
    """Sync wrapper for the CronJob dispatcher."""
    asyncio.run(run_advisor_views())


def _fundamentals_config(settings: object) -> str:
    source = getattr(settings, "fundamentals_source", "edgar")
    if source == "massive":
        return str(getattr(settings, "massive_api_key", ""))
    if source == "edgar":
        return str(getattr(settings, "sec_user_agent", ""))
    return ""
