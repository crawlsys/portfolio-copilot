"""Schwab adapter exceptions.

Structured errors for auth failures, rate limits, and generic API errors.
All inherit from SchwabError to allow broad except clauses.
"""

from __future__ import annotations


class SchwabError(Exception):
    """Base class for all Schwab adapter errors."""


class SchwabAuthError(SchwabError):
    """Authentication/authorization failures.

    Covers:
    - Initial OAuth flow failures (user denied, invalid redirect)
    - Token refresh failures (expired refresh token — the 7-day cliff)
    - Invalid credentials (bad client_id/secret)
    """


class SchwabRateLimitError(SchwabError):
    """API rate limit exceeded. Schwab returns HTTP 429.

    Callers should backoff and retry. In practice Schwab's limits are
    generous for read-only usage (120 req/min per endpoint).
    """

    def __init__(self, message: str = "Rate limit exceeded", retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class SchwabAccountNotFoundError(SchwabError):
    """Account hash not found or not linked to the authenticated user."""


class SchwabSymbolNotFoundError(SchwabError):
    """Symbol not found in Schwab's quote service."""


__all__ = [
    "SchwabAccountNotFoundError",
    "SchwabAuthError",
    "SchwabError",
    "SchwabRateLimitError",
    "SchwabSymbolNotFoundError",
]
