"""Schwab OAuth webhook service tests."""

from __future__ import annotations

import types
from collections import namedtuple

import pytest
from fastapi.testclient import TestClient

import apps.webhook.app as webhook_app
from apps.webhook.app import _PENDING_STATES, create_app

_AuthContext = namedtuple("AuthContext", ["callback_url", "authorization_url", "state"])


@pytest.fixture(autouse=True)
def _clear_states():
    _PENDING_STATES.clear()
    yield
    _PENDING_STATES.clear()


@pytest.fixture
def client(monkeypatch) -> TestClient:
    from apps.common import settings as settings_mod

    settings_mod.get_settings.cache_clear()
    monkeypatch.setenv("SCHWAB_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("SCHWAB_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("SCHWAB_REDIRECT_URI", "https://webhook.example.com/schwab/callback")
    settings_mod.get_settings.cache_clear()
    return TestClient(create_app())


def _fake_schwab(monkeypatch, *, on_exchange=None):
    """Install a fake `schwab.auth` module for get_auth_context/client_from_received_url."""

    def get_auth_context(client_id, callback_url, state=None):
        return _AuthContext(callback_url, f"https://schwab/authorize?state={state or 'S1'}", state or "S1")

    def client_from_received_url(cid, secret, ctx, received_url, token_write_func, **kw):
        if on_exchange:
            on_exchange(token_write_func)
        return types.SimpleNamespace(session=types.SimpleNamespace(close=lambda: None))

    fake = types.ModuleType("schwab.auth")
    fake.get_auth_context = get_auth_context
    fake.client_from_received_url = client_from_received_url
    monkeypatch.setitem(__import__("sys").modules, "schwab.auth", fake)
    monkeypatch.setattr("schwab.auth", fake, raising=False)


def test_healthz(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_login_redirects_and_stores_state(client: TestClient, monkeypatch) -> None:
    _fake_schwab(monkeypatch)
    r = client.get("/schwab/login", follow_redirects=False)
    assert r.status_code == 302
    assert "schwab/authorize" in r.headers["location"]
    assert "S1" in _PENDING_STATES


def test_callback_rejects_unknown_state(client: TestClient, monkeypatch) -> None:
    _fake_schwab(monkeypatch)
    r = client.get("/schwab/callback?code=abc&state=NOPE", follow_redirects=False)
    assert r.status_code == 400


def test_callback_happy_path_writes_secret(client: TestClient, monkeypatch) -> None:
    written = {}

    def on_exchange(token_write_func):
        # schwab-py hands the wrapped {creation_timestamp, token} dict to our writer
        token_write_func({"creation_timestamp": 1, "token": {"refresh_token": "r"}})

    _fake_schwab(monkeypatch, on_exchange=on_exchange)

    calls = []
    monkeypatch.setattr(
        webhook_app.subprocess,
        "run",
        lambda *a, **k: calls.append(a[0]) or types.SimpleNamespace(returncode=0),
    )

    _PENDING_STATES["S1"] = 9e18  # pre-seed a valid state
    r = client.get("/schwab/callback?code=abc&state=S1", follow_redirects=False)
    assert r.status_code == 200
    assert "Schwab connected" in r.text
    # the kubectl patch targeted exactly the one secret
    assert calls and calls[0][:4] == ["kubectl", "patch", "secret", "tracker-schwab-token"]
    assert "S1" not in _PENDING_STATES  # consumed
