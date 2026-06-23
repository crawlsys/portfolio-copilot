"""GenerateBriefing use case.

Collects the day's signals (congressional disclosures, market regime,
portfolio changes) and produces a daily Briefing. The LLM's job is
research/summarization — it NEVER proposes trades (spec §Non-goals).

Two modes:
- LLM mode (LLM_API_KEY set): calls the configured provider for natural-
  language summarization with citations.
- Template mode (no key): structured markdown template with the raw data.
  Still useful; just less polished.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import httpx
from sqlalchemy import select

from trading.adapters.persistence.models import (
    BriefingRow,
    PositionRow,
    TradeDisclosureRow,
)
from trading.domain import (
    AggregateType,
    DomainEvent,
    EventType,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession  # noqa: PLC0415

    from trading.application.common.unit_of_work import UnitOfWork  # noqa: PLC0415
    from trading.application.market_data.refresh_quotes import MarketDataPort  # noqa: PLC0415


@dataclass(frozen=True, slots=True)
class GenerateBriefingCommand:
    correlation_id: object  # UUID
    actor: str
    for_date: date | None = None  # None = today


@dataclass(frozen=True, slots=True)
class BriefingContent:
    briefing_id: str
    briefing_date: date
    period_start: datetime
    period_end: datetime
    summary_markdown: str
    push_excerpt: str
    referenced_disclosure_ids: tuple[str, ...]
    disclosures_count: int
    portfolio_overlaps: int
    market_regime: str
    generated_at: datetime


async def execute(
    cmd: GenerateBriefingCommand,
    uow: UnitOfWork,
    market_data: MarketDataPort | None = None,
    llm_provider: str = "",
    llm_api_key: str = "",
    llm_model: str = "",
) -> BriefingContent:
    """Generate + persist the daily briefing."""
    now = uow.clock.now()
    session = uow.session

    target_date = cmd.for_date or now.date()
    # Look back 72 hours, not just today. STOCK Act disclosures arrive 1-7 days
    # after the trade; filtering to "today only" misses most real data.
    period_end = datetime.combine(target_date + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    period_start = period_end - timedelta(days=7)

    # 1. Gather the rolling window's data
    disclosures = await _fetch_disclosures(session, period_start, period_end)
    held_tickers = await _fetch_held_tickers(session)
    overlaps = [d for d in disclosures if d.symbol and d.symbol in held_tickers]
    market_regime = await _assess_market_regime(market_data)

    # 2. Generate the summary
    context = _BriefingContext(
        date=target_date,
        disclosures=disclosures,
        overlaps=overlaps,
        held_tickers=sorted(held_tickers),
        market_regime=market_regime,
    )

    template_summary, template_excerpt = _generate_template_summary(context)

    if llm_api_key:
        llm_summary, llm_excerpt = await _generate_llm_summary(
            context, llm_provider, llm_api_key, llm_model
        )
        # If the LLM said "no disclosures" but we KNOW there are disclosures,
        # it hallucinated — use the template instead.
        if (
            context.disclosures
            and "no" in llm_summary.lower()[:200]
            and "disclos" in llm_summary.lower()[:200]
        ):
            summary, excerpt = template_summary, template_excerpt
        else:
            summary, excerpt = llm_summary, llm_excerpt
    else:
        summary, excerpt = template_summary, template_excerpt

    # 3. Persist
    briefing_id = f"briefing-{target_date.isoformat()}-{uuid4().hex[:8]}"
    briefing_row = BriefingRow(
        briefing_id=briefing_id,
        briefing_date=datetime.combine(target_date, datetime.min.time(), tzinfo=UTC),
        period_start=period_start,
        period_end=period_end,
        summary_markdown=summary,
        push_excerpt=excerpt,
        referenced_signal_ids=[],
        referenced_disclosure_ids=[d.filing_id for d in disclosures],
        body_blob_key=None,
        generated_at=now,
    )
    session.add(briefing_row)

    # 4. Emit event
    uow.collect(
        DomainEvent(
            type=EventType.BRIEFING_PRODUCED,
            aggregate_id=briefing_id,
            aggregate_type=AggregateType.BRIEFING,
            payload={
                "briefing_id": briefing_id,
                "briefing_date": target_date.isoformat(),
                "disclosures_count": len(disclosures),
                "portfolio_overlaps": len(overlaps),
                "market_regime": market_regime,
                "generated_by": "llm" if llm_api_key else "template",
            },
        )
    )

    return BriefingContent(
        briefing_id=briefing_id,
        briefing_date=target_date,
        period_start=period_start,
        period_end=period_end,
        summary_markdown=summary,
        push_excerpt=excerpt,
        referenced_disclosure_ids=tuple(d.filing_id for d in disclosures),
        disclosures_count=len(disclosures),
        portfolio_overlaps=len(overlaps),
        market_regime=market_regime,
        generated_at=now,
    )


# --- Data gathering ---


async def _fetch_disclosures(
    session: AsyncSession, start: datetime, end: datetime
) -> list[TradeDisclosureRow]:
    result = await session.execute(
        select(TradeDisclosureRow)
        .where(TradeDisclosureRow.disclosure_date >= start)
        .where(TradeDisclosureRow.disclosure_date < end)
        .order_by(TradeDisclosureRow.disclosure_date.desc())
        .limit(100)
    )
    return list(result.scalars().all())


async def _fetch_held_tickers(session: AsyncSession) -> set[str]:
    result = await session.execute(select(PositionRow.symbol).distinct())
    return set(result.scalars().all())


async def _assess_market_regime(
    market_data: MarketDataPort | None,
) -> str:
    """Quick regime assessment from VIX. Returns 'unknown' if no market data."""
    if market_data is None:
        return "unknown"
    try:
        vix = await market_data.get_vix()
        if vix == Decimal("0"):
            return "unknown"
        if vix > Decimal("30"):
            return "risk_off (high vol)"
        if vix < Decimal("15"):
            return "risk_on (low vol)"
        return f"neutral (VIX={vix})"
    except Exception:  # noqa: BLE001
        return "unknown"


# --- Summary generation ---


@dataclass(frozen=True, slots=True)
class _BriefingContext:
    date: date
    disclosures: list[TradeDisclosureRow]
    overlaps: list[TradeDisclosureRow]
    held_tickers: list[str]
    market_regime: str


def _generate_template_summary(ctx: _BriefingContext) -> tuple[str, str]:
    """Structured markdown summary without LLM. Always works."""
    lines = [
        f"# Daily Briefing — {ctx.date.isoformat()}",
        "",
        f"**Market regime:** {ctx.market_regime}",
        f"**New disclosures:** {len(ctx.disclosures)}",
        f"**Portfolio overlaps:** {len(ctx.overlaps)}",
        "",
    ]

    if ctx.overlaps:
        lines.append("## 🎯 Your Holdings — Congressional Activity")
        lines.append("")
        lines.append("| Trader | Ticker | Action | Amount | Traded | Filed |")
        lines.append("|--------|--------|--------|--------|--------|-------|")
        for d in ctx.overlaps[:15]:
            action = "BUY" if "PURCHASE" in d.transaction_type else "SELL"
            amt = (
                f"${d.amount_range_low:,}-${d.amount_range_high:,}"
                if d.amount_range_low
                else "undisclosed"
            )
            lines.append(
                f"| {d.member_name} | **{d.symbol}** | {action} | {amt} | "
                f"{d.transaction_date.date()} | {d.disclosure_date.date()} |"
            )
        lines.append("")

    if ctx.disclosures:
        lines.append("## All Disclosures (this cycle)")
        lines.append("")
        lines.append("| Trader | Ticker | Action | Amount | Filed |")
        lines.append("|--------|--------|--------|--------|-------|")
        for d in ctx.disclosures[:25]:
            sym = d.symbol or d.asset_description[:12]
            action = "BUY" if "PURCHASE" in d.transaction_type else "SELL"
            amt = f"${d.amount_range_low:,}" if d.amount_range_low else "??"
            lines.append(
                f"| {d.member_name} | {sym} | {action} | {amt} | {d.disclosure_date.date()} |"
            )

    # Push excerpt: short, actionable
    overlap_text = f"{len(ctx.overlaps)} overlap(s) with your portfolio. " if ctx.overlaps else ""
    excerpt = (
        f"📊 {ctx.date.isoformat()}: {len(ctx.disclosures)} new disclosure(s). "
        f"{overlap_text}Regime: {ctx.market_regime}."
    )

    return "\n".join(lines), excerpt


async def _generate_llm_summary(
    ctx: _BriefingContext,
    provider: str,
    api_key: str,
    model: str,
) -> tuple[str, str]:
    """LLM-generated summary with natural language + citations.

    Falls back to template if the LLM call fails. The LLM is explicitly
    instructed NOT to propose trades — it summarizes and contextualizes.
    """
    template_summary, template_excerpt = _generate_template_summary(ctx)

    try:
        if provider == "anthropic":
            return await _call_anthropic(ctx, api_key, model or "claude-sonnet-4-20250504")
        if provider == "litellm":
            return await _call_litellm(ctx, api_key, model or "local-fast")
        if provider == "openai":
            return await _call_openai(ctx, api_key, model or "gpt-4o")
        # Unknown provider — fall back
        return template_summary, template_excerpt
    except Exception:  # noqa: BLE001
        # LLM failed — template is always safe
        return template_summary, template_excerpt


async def _call_anthropic(ctx: _BriefingContext, api_key: str, model: str) -> tuple[str, str]:
    """Call Anthropic Claude for the briefing summary."""
    import httpx  # noqa: PLC0415

    prompt = _build_llm_prompt(ctx)
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 4000,
                "system": (
                    "You are a financial research assistant analyzing Congressional trade "
                    "disclosures for a sophisticated investor. Write a detailed briefing "
                    "(3-5 paragraphs) covering: (1) the most significant trades and what they "
                    "signal, (2) patterns by trader, (3) sector concentration, (4) disclosure "
                    "lag anomalies, and (5) overlaps with held tickers. Be specific with names, "
                    "tickers, and amounts. Do NOT propose trades or give advice. End with PUSH: "
                    "followed by a 2-3 sentence summary."
                ),
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        data = response.json()
        text = data["content"][0]["text"]

    # Extract push excerpt
    push = template_excerpt_fallback(ctx)
    if "PUSH:" in text:
        parts = text.rsplit("PUSH:", 1)
        text = parts[0].rstrip()
        push = parts[1].strip()

    return text, push


async def _call_openai(ctx: _BriefingContext, api_key: str, model: str) -> tuple[str, str]:
    """Call OpenAI for the briefing summary."""
    import httpx  # noqa: PLC0415

    prompt = _build_llm_prompt(ctx)
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 4000,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a financial research assistant analyzing Congressional trade "
                            "disclosures for a sophisticated investor. Write a detailed briefing "
                            "(3-5 paragraphs) covering: (1) the most significant trades and what they "
                            "signal, (2) patterns by trader — are they repeating, diversifying, or "
                            "liquidating? (3) sector concentration trends, (4) disclosure lag anomalies "
                            "(trades filed unusually fast or slow), and (5) notable overlaps with the "
                            "investor's held tickers. Be specific with names, tickers, and amounts. "
                            "You MUST NOT propose trades or give investment advice. End with 'PUSH: '"
                            "followed by a 2-3 sentence push notification summary."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            },
        )
        response.raise_for_status()
        data = response.json()
        text = data["choices"][0]["message"]["content"]

    push = template_excerpt_fallback(ctx)
    if "PUSH:" in text:
        parts = text.rsplit("PUSH:", 1)
        text = parts[0].rstrip()
        push = parts[1].strip()

    return text, push


async def _call_litellm(ctx: _BriefingContext, api_key: str, model: str) -> tuple[str, str]:
    """Call a LiteLLM gateway (OpenAI-compatible endpoint).

    The gateway routes to local models (local-strong, local-fast) or any
    configured provider. Base URL comes from LITELLM_BASE_URL env or defaults
    to the k3s NodePort.
    """
    base_url = os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:30400")
    prompt = _build_llm_prompt(ctx)
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{base_url}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 4000,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a financial research assistant. Produce a CONCISE briefing using "
                            "markdown tables and short bullets — NOT long paragraphs. Format:\n"
                            "1. One-sentence summary of the filing cycle.\n"
                            "2. A markdown table: | Trader | Ticker | Action | Amount | Traded | Filed | Lag |\n"
                            "   Group by trader. Mark portfolio overlaps with ⚠️.\n"
                            "3. Short bullet list (max 5) of notable patterns or anomalies.\n"
                            "4. One sentence on sector trend.\n"
                            "Keep it scannable. No paragraphs longer than 2 sentences. "
                            "Do NOT propose trades or give advice. "
                            "End with PUSH: followed by a 1-2 sentence summary."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            },
        )
        response.raise_for_status()
        data = response.json()
        text = data["choices"][0]["message"]["content"]

    push = template_excerpt_fallback(ctx)
    if "PUSH:" in text:
        parts = text.rsplit("PUSH:", 1)
        text = parts[0].rstrip()
        push = parts[1].strip()

    return text, push


def _build_llm_prompt(ctx: _BriefingContext) -> str:
    """Build the user prompt for the LLM from the briefing context."""
    lines = [
        f"Date: {ctx.date.isoformat()}",
        f"Market regime: {ctx.market_regime}",
        f"Held tickers: {', '.join(ctx.held_tickers[:30])}",
        "",
        f"New Congressional trade disclosures ({len(ctx.disclosures)} total):",
        "",
    ]

    for d in ctx.disclosures[:30]:
        overlap = " ⚠️ OVERLAPS YOUR PORTFOLIO" if d in ctx.overlaps else ""
        sym = d.symbol or d.asset_description
        lines.append(
            f"- {d.member_name} ({d.transaction_type}) {sym} "
            f"${d.amount_range_low:,}-${d.amount_range_high:,} "
            f"(traded {d.transaction_date.date()}, filed {d.disclosure_date.date()}, "
            f"lag={d.lag_days if hasattr(d, 'lag_days') else '?'}d){overlap}"
        )

    lines.extend(
        [
            "",
            "Summarize these disclosures. Highlight any that overlap the held tickers. "
            "Note the disclosure lag (trades are 30-45 days old by law). Do NOT "
            "recommend trades.",
        ]
    )
    return "\n".join(lines)


def template_excerpt_fallback(ctx: _BriefingContext) -> str:
    _, excerpt = _generate_template_summary(ctx)
    return excerpt


__all__ = [
    "GenerateBriefingCommand",
    "BriefingContent",
    "execute",
]
