"""Tests for Congressional disclosure API routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from apps.api.app import create_app
from apps.common.settings import get_settings
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from trading.adapters.persistence.models import (
    BrokerAccountRow,
    MemberRow,
    PositionRow,
    QuoteCacheRow,
    TradeDisclosureRow,
)

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not settings.database_url,
    reason="DATABASE_URL required for congressional route tests",
)


@pytest.fixture()
def engine():
    eng = create_engine(settings.database_url, poolclass=NullPool)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def seeded_congressional_data(engine) -> None:  # type: ignore[no-untyped-def]
    now = datetime(2026, 6, 21, 14, 30, tzinfo=UTC)
    with Session(engine) as session:
        _cleanup(session)
        session.add_all(
            [
                MemberRow(
                    member_id="test-pelosi",
                    name="Nancy Pelosi",
                    chamber="house",
                    party="Democratic",
                    state="CA",
                    district="11",
                    committees=["Appropriations"],
                ),
                MemberRow(
                    member_id="test-crapo",
                    name="Mike Crapo",
                    chamber="senate",
                    party="Republican",
                    state="ID",
                    district=None,
                    committees=["Finance"],
                ),
                BrokerAccountRow(
                    account_id="test-account",
                    nickname="Test",
                    masked_schwab_id="****9999",
                    account_type="TAXABLE",
                    margin_enabled=False,
                    allowed_instruments=["EQUITY"],
                    is_paper=True,
                ),
                PositionRow(
                    account_id="test-account",
                    symbol="AAPL",
                    asset_class="EQUITY",
                    quantity=Decimal("10"),
                    average_cost=Decimal("150"),
                    market_value=Decimal("2000"),
                    unrealized_pnl=Decimal("500"),
                    as_of=now,
                ),
                QuoteCacheRow(
                    symbol="AAPL",
                    bid=Decimal("209.90"),
                    ask=Decimal("210.10"),
                    last=Decimal("210.00"),
                    volume=1234,
                    observed_at=now,
                    updated_at=now,
                ),
            ]
        )
        session.add_all(
            [
                TradeDisclosureRow(
                    filing_id="test-filing-aapl",
                    member_id="test-pelosi",
                    member_name="Nancy Pelosi",
                    symbol="AAPL",
                    asset_class="EQUITY",
                    asset_description="Apple Inc.",
                    transaction_type="BUY",
                    transaction_date=now - timedelta(days=12),
                    disclosure_date=now - timedelta(days=2),
                    amount_range_low=100001,
                    amount_range_high=250000,
                    raw_blob_key="test/aapl.json",
                    ingested_at=now,
                ),
                TradeDisclosureRow(
                    filing_id="test-filing-jpm",
                    member_id="test-crapo",
                    member_name="Mike Crapo",
                    symbol="JPM",
                    asset_class="EQUITY",
                    asset_description="JPMorgan Chase & Co.",
                    transaction_type="SELL",
                    transaction_date=now - timedelta(days=20),
                    disclosure_date=now - timedelta(days=5),
                    amount_range_low=15001,
                    amount_range_high=50000,
                    raw_blob_key="test/jpm.json",
                    ingested_at=now,
                ),
            ]
        )
        session.commit()
    yield
    with Session(engine) as session:
        _cleanup(session)
        session.commit()


@pytest.fixture()
def client() -> TestClient:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_list_disclosures_filters_by_symbol(client: TestClient) -> None:
    response = client.get(
        "/congressional/disclosures",
        params={"symbol": "AAPL", "member": "test-pelosi"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["filingId"] for item in body] == ["test-filing-aapl"]
    assert body[0]["member"]["name"] == "Nancy Pelosi"
    assert body[0]["lagDays"] == 10


def test_get_disclosure_detail(client: TestClient) -> None:
    response = client.get("/congressional/disclosures/test-filing-aapl")

    assert response.status_code == 200
    body = response.json()
    assert body["filingId"] == "test-filing-aapl"
    assert body["currentPrice"] == "210.0000"
    assert body["inPortfolio"] is True
    assert body["rawBlobKey"] == "test/aapl.json"


def test_list_members(client: TestClient) -> None:
    response = client.get("/congressional/members")

    assert response.status_code == 200
    names = {item["name"] for item in response.json()}
    assert {"Nancy Pelosi", "Mike Crapo"} <= names


def test_get_member_detail(client: TestClient) -> None:
    response = client.get("/congressional/members/test-pelosi")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Nancy Pelosi"
    assert body["recentDisclosures"][0]["filingId"] == "test-filing-aapl"


def test_portfolio_overlap(client: TestClient) -> None:
    response = client.get("/congressional/portfolio-overlap")

    assert response.status_code == 200
    body = response.json()
    aapl = next(item for item in body if item["symbol"] == "AAPL")
    assert aapl["memberCount"] >= 1
    assert "test-filing-aapl" in {disclosure["filingId"] for disclosure in aapl["disclosures"]}


def _cleanup(session: Session) -> None:
    session.execute(text("DELETE FROM trade_disclosures WHERE filing_id LIKE 'test-%'"))
    session.execute(text("DELETE FROM positions WHERE account_id = 'test-account'"))
    session.execute(text("DELETE FROM broker_accounts WHERE account_id = 'test-account'"))
    session.execute(text("DELETE FROM quote_cache WHERE symbol = 'AAPL'"))
    session.execute(text("DELETE FROM members WHERE member_id IN ('test-pelosi', 'test-crapo')"))
