"""Pytest configuration.

- Socket blocking: when PYTEST_DISABLE_SOCKET=1, any real network call fails
  the test. Cassettes (VCR) intercept HTTP before the socket layer, so they
  still work in CI.
- `trading_vcr` session fixture: VCR.py configured for record-once-replay.
  Tests use it as `@pytest.mark.vcr(trading_vcr)` or by passing the fixture
  into their client constructor.
- Async mode is set to 'auto' in pyproject.toml.
"""

from __future__ import annotations

import os
import socket

import pytest
import vcr as vcr_module


def pytest_configure(config: pytest.Config) -> None:
    if os.environ.get("PYTEST_DISABLE_SOCKET") == "1":
        _install_socket_blocker()


def _install_socket_blocker() -> None:
    """Block all real network connections; tests must use VCR cassettes or fakes.

    Exception: AF_UNIX socketpairs (used by asyncio's internal self-pipe and
    by some test helpers) are allowed. The blocker is about preventing real
    network I/O, not breaking the event loop.
    """

    _orig = socket.socket

    class _BlockedSocket(_orig):  # type: ignore[misc, valid-type]
        def __init__(self, *args: object, **kwargs: object) -> None:
            # Allow AF_UNIX — asyncio uses socket.socketpair(AF_UNIX) for its
            # internal wakeup fd. Without this every async test fails to even
            # construct an event loop.
            family = args[0] if args else kwargs.get("family", socket.AF_INET)
            if family == socket.AF_UNIX:
                super().__init__(*args, **kwargs)  # type: ignore[misc]
                return
            raise RuntimeError(
                "Real network socket blocked by PYTEST_DISABLE_SOCKET=1. "
                "Use a VCR cassette or a fake adapter."
            )

    socket.socket = _BlockedSocket  # type: ignore[misc]

    # Also patch socketpair to allow AF_UNIX (the only family it uses by default)
    _orig_pair = socket.socketpair

    def _blocked_socketpair(*args: object, **kwargs: object) -> object:
        # socketpair defaults to AF_UNIX; let it through. We only block
        # if someone explicitly asks for an INET pair.
        family = args[0] if args else kwargs.get("family", socket.AF_UNIX)
        if family == socket.AF_UNIX:
            return _orig_pair(*args, **kwargs)  # type: ignore[no-any-return]
        raise RuntimeError("Real network socketpair blocked by PYTEST_DISABLE_SOCKET=1.")

    socket.socketpair = _blocked_socketpair  # type: ignore[assignment]


@pytest.fixture(scope="session")
def trading_vcr() -> vcr_module.VCR:
    """Session-scoped VCR. Cassette library dir: tests/adapters/cassettes/.

    Record mode:
    - Default ('once'): record a cassette if absent, replay on subsequent runs.
    - CI sets VCR_RECORD_MODE=none so missing cassettes fail loudly.
    - Local refresh: set VCR_RECORD_MODE=new_episodes or all to re-record.

    All sensitive headers/query params are scrubbed before writing to disk.
    """
    return vcr_module.VCR(
        cassette_library_dir="tests/adapters/cassettes",
        record_mode=os.environ.get("VCR_RECORD_MODE", "once"),
        filter_headers=["authorization", "x-api-key", "api-key", "cookie"],
        filter_query_parameters=["apikey", "apiKey", "token", "access_token"],
        filter_post_data_parameters=["apikey", "apiKey", "token"],
        decode_compressed_response=True,
        match_on=["method", "scheme", "host", "port", "path", "query"],
    )
