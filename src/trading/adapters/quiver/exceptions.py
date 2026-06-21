"""Quiver Quant adapter exceptions."""

from __future__ import annotations


class QuiverError(Exception):
    """Base error for Quiver API failures."""


class QuiverAuthError(QuiverError):
    """Raised when Quiver rejects the supplied API key."""


class QuiverRateLimitError(QuiverError):
    """Raised when Quiver returns HTTP 429."""

    def __init__(self, message: str, retry_after: str | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class QuiverParseError(QuiverError):
    """Raised when a Quiver response record cannot be parsed."""
