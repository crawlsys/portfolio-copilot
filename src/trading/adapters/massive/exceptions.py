"""Massive.com adapter exceptions."""

from __future__ import annotations


class MassiveError(RuntimeError):
    """Base exception for Massive adapter failures."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class MassiveAuthError(MassiveError):
    """Raised when Massive rejects credentials or plan access."""


class MassiveRateLimitError(MassiveError):
    """Raised when Massive returns HTTP 429."""

    def __init__(
        self,
        message: str,
        *,
        retry_after: str | None = None,
        rate_limit: str | None = None,
        rate_limit_remaining: str | None = None,
        rate_limit_reset: str | None = None,
    ) -> None:
        super().__init__(message, status_code=429)
        self.retry_after = retry_after
        self.rate_limit = rate_limit
        self.rate_limit_remaining = rate_limit_remaining
        self.rate_limit_reset = rate_limit_reset
