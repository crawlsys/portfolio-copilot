"""Smoke tests for the FastAPI app.

Uses FastAPI's TestClient against the FakeBroker (no DB needed for
account reads). Verifies:
- App boots via create_app()
- /health/live and /health/ready return 200
- GET /portfolio/{account_id} returns seeded fake data
- GET /portfolio/unknown returns 404
- POST /portfolio/{account_id}/refresh returns 503 when no DB configured
- The OpenAPI schema is non-empty and has the expected routes
"""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal

import pytest
from apps.api.app import create_app
from fastapi.testclient import TestClient

from trading.adapters.fake.broker import make_default_fake_broker


@pytest.fixture()
def client() -> TestClient:
    app = create_app()
    # The lifespan builds composition; TestClient triggers it via `with`.
    with TestClient(app) as c:
        yield c


def test_app_boots(client: TestClient) -> None:
    assert client.app.title == "tracker"


def test_health_live(client: TestClient) -> None:
    r = client.get("/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_ready(client: TestClient) -> None:
    r = client.get("/health/ready")
    assert r.status_code == 200


def test_get_seeded_account(client: TestClient) -> None:
    """The FakeBroker's default account (real or sample) is reachable."""
    account_id = _first_account_id()

    r = client.get(f"/portfolio/{account_id}")
    assert r.status_code == 200, f"GET /portfolio/{account_id} failed: {r.text}"
    body = r.json()
    assert body["accountId"] == account_id
    assert Decimal(body["cash"]) >= 0
    assert len(body["positions"]) >= 1


def _first_account_id() -> str:
    """Discover the FakeBroker's first account ID (real or sample)."""
    broker = make_default_fake_broker()
    accts = asyncio.run(broker.get_accounts())
    assert len(accts) >= 1
    return accts[0].account_id


def test_unknown_account_returns_404(client: TestClient) -> None:
    r = client.get("/portfolio/does-not-exist")
    assert r.status_code == 404


@pytest.mark.skipif(
    bool(os.environ.get("DATABASE_URL")),
    reason="Refresh needs the no-DB 503 path; when DB is set this test is N/A",
)
def test_refresh_without_db_returns_503(client: TestClient) -> None:
    r = client.post(f"/portfolio/{_first_account_id()}/refresh")
    assert r.status_code == 503


def test_openapi_has_expected_routes(client: TestClient) -> None:
    schema = client.app.openapi()
    paths = set(schema["paths"].keys())
    assert "/health/live" in paths
    assert "/health/ready" in paths
    assert "/portfolio/{account_id}" in paths
    assert "/portfolio/{account_id}/refresh" in paths


def test_openapi_has_no_trading_routes(client: TestClient) -> None:
    """Spec invariant: no trading routes. If anyone adds /order, this fails."""
    schema = client.app.openapi()
    for path in schema["paths"]:
        path_lower = path.lower()
        forbidden = ("/order", "/trade", "/buy", "/sell", "/submit", "/execute", "/approve")
        for bad in forbidden:
            assert bad not in path_lower, (
                f"Found trading route {path} — spec §Non-goals: no live trade execution. "
                "If execution is being activated, see spec §Execution (stub)."
            )
