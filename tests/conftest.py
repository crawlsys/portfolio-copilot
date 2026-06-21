"""Pytest configuration.

- Socket blocking: when PYTEST_DISABLE_SOCKET=1, any real network call fails
  the test. Cassettes (VCR) intercept HTTP before the socket layer, so they
  still work in CI.
- Async mode is set to 'auto' in pyproject.toml.
"""
from __future__ import annotations

import os
import socket

import pytest


def pytest_configure(config: pytest.Config) -> None:
    if os.environ.get("PYTEST_DISABLE_SOCKET") == "1":
        _install_socket_blocker()


def _install_socket_blocker() -> None:
    """Block all real socket connections; tests must use VCR cassettes or fakes."""

    _orig = socket.socket

    class _BlockedSocket(_orig):  # type: ignore[misc, valid-type]
        def __init__(self, *args: object, **kwargs: object) -> None:
            # Allow Unix domain sockets for things like postgres in CI? No —
            # we use TCP. If we ever need UDS, allow AF_UNIX here.
            raise RuntimeError(
                "Real socket blocked by PYTEST_DISABLE_SOCKET=1. "
                "Use a VCR cassette or a fake adapter."
            )

    socket.socket = _BlockedSocket  # type: ignore[misc]
