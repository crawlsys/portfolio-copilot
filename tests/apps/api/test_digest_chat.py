"""Tests for the digest chat streaming endpoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from apps.api.app import create_app
from apps.api.routes import digest_chat
from apps.common.settings import get_settings
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from trading.adapters.persistence.models import (
    BrokerAccountRow,
    DigestRow,
    PositionRow,
)

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not settings.database_url,
    reason="DATABASE_URL required for digest chat tests",
)


@pytest.fixture()
def engine():
    eng = create_engine(settings.database_url, poolclass=NullPool)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def seeded(engine, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    now = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)
    with Session(engine) as session:
        _cleanup(session)
        session.add(
            BrokerAccountRow(
                account_id="chat-test-account",
                nickname="ChatTest",
                masked_schwab_id="****0000",
                account_type="TAXABLE",
                margin_enabled=False,
                allowed_instruments=["EQUITY"],
                is_paper=True,
            )
        )
        session.add(
            PositionRow(
                account_id="chat-test-account",
                symbol="VTI",
                asset_class="EQUITY",
                quantity=Decimal("100"),
                average_cost=Decimal("250"),
                market_value=Decimal("28000"),
                unrealized_pnl=Decimal("3000"),
                as_of=now,
            )
        )
        session.add(
            DigestRow(
                digest_id="chat-test-digest",
                digest_date=now,
                summary_markdown="## Action of the Day\nBUY VTI to deploy cash.",
                push_excerpt="Buy VTI.",
                model="anthropic/claude-opus-4.8",
                net_liquidation="28000",
                cash_to_deploy="50000",
                disclosures_count=0,
                body_blob_key=None,
                generated_at=now,
            )
        )
        session.commit()
    # Never touch the network for VIX/regime in tests.
    monkeypatch.setattr(digest_chat, "_assess_market_regime", _fake_regime)
    monkeypatch.setattr(get_settings(), "openrouter_api_key", "test-key")
    digest_chat._recent_calls.clear()
    yield
    with Session(engine) as session:
        _cleanup(session)
        session.commit()


async def _fake_regime(_market_data) -> str:  # type: ignore[no-untyped-def]
    return "neutral"


@pytest.fixture()
def client() -> TestClient:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def _patch_stream(monkeypatch, captured: dict) -> None:
    async def fake_stream(api_key, model, messages) -> AsyncIterator[str]:  # type: ignore[no-untyped-def]
        captured["model"] = model
        captured["messages"] = messages
        yield 'data: "Hello"\n\n'
        yield 'data: " there"\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(digest_chat, "_stream_openrouter", fake_stream)


def test_chat_streams_tokens_with_context(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict = {}
    _patch_stream(monkeypatch, captured)

    resp = client.post(
        "/digest/chat",
        json={"messages": [{"role": "user", "content": "Should I buy VTI?"}]},
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert "Hello" in resp.text and "there" in resp.text
    assert resp.text.strip().endswith("data: [DONE]")

    # Context is injected into the system message: holdings + recent digest.
    system = captured["messages"][0]["content"]
    assert captured["messages"][0]["role"] == "system"
    assert "VTI" in system
    assert "BUY VTI to deploy cash" in system  # the recent digest body
    # Conversation is forwarded after the system message.
    assert captured["messages"][-1] == {"role": "user", "content": "Should I buy VTI?"}


def test_model_allowlist_falls_back(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict = {}
    _patch_stream(monkeypatch, captured)

    resp = client.post(
        "/digest/chat",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "model": "evil/free-model",
        },
    )
    assert resp.status_code == 200
    assert captured["model"] == "anthropic/claude-opus-4.8"


def test_model_allowlist_honors_valid_pick(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict = {}
    _patch_stream(monkeypatch, captured)

    resp = client.post(
        "/digest/chat",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "model": "anthropic/claude-sonnet-4.6",
        },
    )
    assert resp.status_code == 200
    assert captured["model"] == "anthropic/claude-sonnet-4.6"


def test_empty_messages_rejected(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_stream(monkeypatch, {})
    resp = client.post("/digest/chat", json={"messages": []})
    assert resp.status_code == 400


def test_rate_limit_returns_429() -> None:
    digest_chat._recent_calls.clear()
    for _ in range(digest_chat._RATE_MAX):
        digest_chat._rate_limit()
    with pytest.raises(digest_chat.HTTPException) as exc:
        digest_chat._rate_limit()
    assert exc.value.status_code == 429
    digest_chat._recent_calls.clear()


def _cleanup(session: Session) -> None:
    session.execute(text("DELETE FROM positions WHERE account_id = 'chat-test-account'"))
    session.execute(text("DELETE FROM broker_accounts WHERE account_id = 'chat-test-account'"))
    session.execute(text("DELETE FROM digests WHERE digest_id = 'chat-test-digest'"))
