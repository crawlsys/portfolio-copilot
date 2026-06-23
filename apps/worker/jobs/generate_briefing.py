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
from trading.application.market_data.refresh_quotes import MarketDataPort, NoMarketData
from trading.application.signals.generate_briefing import (
    GenerateBriefingCommand,
    execute,
)
from trading.domain import Severity

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

        # Push the briefing via Pushover (if configured)
        if settings.push_provider == "pushover" and settings.pushover_api_token:
            from trading.adapters.notifications.pushover import PushoverNotifier  # noqa: PLC0415

            notifier = PushoverNotifier(
                api_token=settings.pushover_api_token,
                user_key=settings.pushover_user_key,
            )

            # Convert markdown to Pushover-compatible HTML, then trim to
            # Pushover's 1024-char message limit on a <br> boundary so we
            # never cut a table row (and its open tags) in half.
            html_body = _markdown_to_pushover_html(result.summary_markdown)
            html_body = _trim_pushover_html(html_body, limit=1024)

            await notifier.send(
                title=f"📊 Congressional Briefing — {result.briefing_date.isoformat()}",
                body=html_body,
                severity=Severity.INFO,
                tags=["briefing", "congress"],
                click_url="https://trackdash.example.com",
                html=True,
            )
            await notifier.aclose()
            _log.info("briefing pushed via Pushover")
    finally:
        await engine.dispose()


# Header aliases -> canonical column key. Matched as substrings against the
# lowercased header cell, so "Transaction Date" still maps to "traded".
_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "trader": ("trader", "name", "member", "representative", "senator"),
    "ticker": ("ticker", "symbol", "asset"),
    "action": ("action", "type", "side", "transaction"),
    "amount": ("amount", "range", "value", "size"),
    "traded": ("traded", "transaction date", "tx date", "trade date"),
    "filed": ("filed", "disclosure date", "disclosed"),
    "lag": ("lag",),
}


def _strip_inline_md(s: str) -> str:
    """Strip markdown emphasis + overlap markers for use inside HTML tags."""
    import re

    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"(?<!\*)\*([^\s*][^*]*?)\*(?!\*)", r"\1", s)
    s = re.sub(r"`(.+?)`", r"\1", s)
    s = s.replace("⚠️", "").replace("⚠", "")
    return s.strip()


def _is_separator_row(line: str) -> bool:
    """True for a markdown table separator like |---|:--:|."""
    stripped = line.strip()
    return bool(stripped) and "-" in stripped and bool(
        __import__("re").match(r"^\|?[-:\s|]+$", stripped)
    )


def _action_color(action: str) -> str:
    a = action.upper()
    if "BUY" in a or "PURCH" in a or "ACQUI" in a:
        return "green"
    if "SELL" in a or "SALE" in a or "EXCH" in a:
        return "red"
    return "orange"


def _parse_cells(line: str) -> list[str]:
    """Split a markdown table row into stripped, emphasis-free cells."""
    inner = line.strip().strip("|")
    return [_strip_inline_md(c.strip()) for c in inner.split("|")]


def _render_table_block(header_row: str, data_rows: list[str]) -> str:
    """Render a markdown table as a stack of colored HTML lines.

    Each data row becomes one line, e.g.:
        <b>Moskowitz</b> <font color="green"><b>BUY</b></font> <b>GILD</b> $1,001-$15,000 <i>traded 6/15, filed 6/22</i>
    """
    header_cells = _parse_cells(header_row)
    col_map: dict[str, int] = {}
    for idx, cell in enumerate(header_cells):
        low = cell.lower()
        for key, aliases in _HEADER_ALIASES.items():
            if key in col_map:
                continue
            if any(a in low for a in aliases):
                col_map[key] = idx

    rendered: list[str] = []
    for row in data_rows:
        cells = _parse_cells(row)
        if not any(cells):
            continue

        def cell(key: str) -> str:
            i = col_map.get(key)
            return cells[i] if i is not None and i < len(cells) else ""

        trader = cell("trader")
        action = cell("action")
        ticker = cell("ticker")
        amount = cell("amount")
        traded = cell("traded")
        filed = cell("filed")
        lag = cell("lag")

        # Unrecognized structure — fall back to joining raw cells so nothing
        # is silently dropped.
        if not trader and not action and not ticker:
            joined = " ".join(c for c in cells if c)
            if joined:
                rendered.append(joined)
            continue

        parts: list[str] = []
        if trader:
            parts.append(f"<b>{trader}</b>")
        if action:
            parts.append(f'<font color="{_action_color(action)}"><b>{action}</b></font>')
        if ticker:
            parts.append(f"<b>{ticker}</b>")
        if amount:
            parts.append(amount)

        detail: list[str] = []
        if traded:
            detail.append(f"traded {traded}")
        if filed:
            detail.append(f"filed {filed}")
        if lag:
            detail.append(f"{lag} lag")
        if detail:
            parts.append(f"<i>{', '.join(detail)}</i>")

        line = " ".join(parts)
        # Mark overlap rows (LLM may put ⚠️ inline; template adds ⚠️ prefix).
        if "⚠️" in row or "⚠" in row:
            line = "⚠️ " + line
        rendered.append(line)

    return "<br>".join(rendered)


def _convert_line(line: str) -> str:
    """Convert a non-table markdown line to inline HTML."""
    import re

    converted = line
    # Strip leading list markers (-, *, •, 1.) — Pushover has no <li>.
    converted = re.sub(r"^\s*([-*•]|\d+\.)\s+", "", converted)
    converted = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", converted)
    converted = re.sub(r"(?<!\*)\*([^\s*][^*]*?)\*(?!\*)", r"<i>\1</i>", converted)
    converted = re.sub(r"`(.+?)`", r"<code>\1</code>", converted)
    return converted


def _markdown_to_pushover_html(md: str) -> str:
    """Convert briefing markdown to Pushover-compatible HTML.

    Pushover supports a small HTML subset: b, i, u, font(color), a, s, code,
    pre, br. Tables aren't supported, and on a phone <pre> tables wrap badly.
    So we collapse each markdown table row into a single colored line:

        <b>Moskowitz</b> <font color="green"><b>BUY</b></font> <b>GILD</b> $1,001-$15,000

    BUY → green, SELL → red. Headers (## Title) become bold lines. The LLM
    and the template both emit tables with the columns we recognize.
    """
    import re

    out: list[str] = []
    lines = md.split("\n")
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # --- Table block -------------------------------------------------
        if stripped.startswith("|") and "|" in stripped[1:]:
            block: list[str] = []
            while (
                i < n
                and lines[i].strip().startswith("|")
                and "|" in lines[i].strip()[1:]
            ):
                block.append(lines[i])
                i += 1
            if len(block) >= 2:
                header = block[0]
                data_rows = [r for r in block[1:] if not _is_separator_row(r)]
                out.append(_render_table_block(header, data_rows))
            else:
                cells = _parse_cells(block[0])
                out.append(" ".join(cells))
            continue

        # --- Section header ----------------------------------------------
        header_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if header_match:
            title = _strip_inline_md(header_match.group(2))
            out.append(f"<b>{title}</b>")
            out.append("")  # spacer -> visual break after a header
            i += 1
            continue

        # --- Blank line ---------------------------------------------------
        if stripped == "":
            out.append("")
            i += 1
            continue

        # --- Ordinary paragraph line -------------------------------------
        out.append(_convert_line(stripped))
        i += 1

    html = "<br>".join(out)
    # Collapse runs of blank-line spacers into a single visual break.
    while "<br><br><br>" in html:
        html = html.replace("<br><br><br>", "<br><br>")
    return html


def _trim_pushover_html(html: str, limit: int = 1024) -> str:
    """Trim HTML to Pushover's message limit on a <br> boundary.

    Cutting at <br> keeps every line self-contained, so we never leave an
    unclosed <font> or <b>. Appends an ellipsis if trimmed.
    """
    if len(html) <= limit:
        return html
    ellipsis = "…"
    # Leave room for the ellipsis when searching.
    cut = html.rfind("<br>", 0, limit - len(ellipsis))
    if cut == -1:
        cut = html.rfind(" ", 0, limit - len(ellipsis))
    if cut == -1:
        cut = max(0, limit - len(ellipsis))
    return html[:cut].rstrip() + ellipsis


def run_briefing_sync() -> None:
    """Sync wrapper for APScheduler."""
    asyncio.run(run_briefing())
