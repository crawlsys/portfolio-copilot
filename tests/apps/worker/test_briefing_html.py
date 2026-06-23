"""Tests for the briefing markdown → Pushover HTML converter.

Pushover supports a tiny HTML subset (b, i, font color, br) but no tables.
The converter collapses each markdown table row into a single colored line
so the notification reads well on a phone. These tests pin that behavior.
"""

from __future__ import annotations

import pytest

from apps.worker.jobs.generate_briefing import (
    _markdown_to_pushover_html,
    _trim_pushover_html,
)


def test_table_becomes_colored_lines() -> None:
    md = (
        "| Trader | Ticker | Action | Amount |\n"
        "|--------|--------|--------|--------|\n"
        "| Moskowitz | GILD | BUY | $1,001-$15,000 |\n"
        "| Van Epps | MSFT | SELL | $15,001-$50,000 |\n"
    )
    html = _markdown_to_pushover_html(md)

    assert "<b>Moskowitz</b>" in html
    assert '<font color="green"><b>BUY</b></font>' in html
    assert '<font color="red"><b>SELL</b></font>' in html
    assert "<b>GILD</b>" in html
    assert "<b>MSFT</b>" in html
    # No <pre> blocks — those wrap badly on mobile.
    assert "<pre>" not in html


def test_separator_row_is_dropped() -> None:
    md = "| A | B |\n|---|---|\n| 1 | 2 |\n"
    html = _markdown_to_pushover_html(md)
    assert "---" not in html


def test_llm_header_aliases_recognized() -> None:
    """LLM tables use 'Representative', 'Symbol', 'Side', 'Transaction Date'."""
    md = (
        "| Representative | Symbol | Side | Transaction Date |\n"
        "|---|---|---|---|\n"
        "| Pelosi | NVDA | Purchase | 2026-06-10 |\n"
    )
    html = _markdown_to_pushover_html(md)
    assert "<b>Pelosi</b>" in html
    assert '<font color="green"><b>Purchase</b></font>' in html
    assert "<b>NVDA</b>" in html
    assert "traded 2026-06-10" in html


def test_overlap_marker_appears_once() -> None:
    """LLM may inline ⚠️; the template prefixes it. We want exactly one."""
    md = (
        "| Trader | Ticker | Action | Amount |\n"
        "|---|---|---|---|\n"
        "| Moskowitz | GILD | BUY | $1,001 ⚠️ |\n"
    )
    html = _markdown_to_pushover_html(md)
    assert html.count("⚠️") == 1
    assert html.startswith("⚠️")


def test_bold_and_headers_and_bullets() -> None:
    md = (
        "# Title\n"
        "\n"
        "**Key:** value\n"
        "- **Bullet**: detail\n"
    )
    html = _markdown_to_pushover_html(md)
    assert "<b>Title</b>" in html
    assert "<b>Key:</b> value" in html
    # Bullet marker stripped, bold preserved.
    assert "- " not in html
    assert "<b>Bullet</b>: detail" in html


def test_trim_respects_limit_and_keeps_tags_closed() -> None:
    html = "<b>x</b><br>" * 400  # ~2400 chars
    trimmed = _trim_pushover_html(html, limit=1024)
    assert len(trimmed) <= 1024
    # Trimmed on a <br> boundary + ellipsis, so no dangling open tags.
    assert trimmed.endswith("…")
    # Every <b> that opens has a closing </b> before the cut.
    assert trimmed.count("<b>") == trimmed.count("</b>")


def test_trim_noop_when_under_limit() -> None:
    html = "short"
    assert _trim_pushover_html(html, limit=1024) == "short"
