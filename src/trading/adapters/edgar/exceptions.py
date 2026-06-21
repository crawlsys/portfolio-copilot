"""EDGAR adapter exceptions."""

from __future__ import annotations


class EDGARError(Exception):
    """Base exception for EDGAR API errors."""


class EDGARAuthError(EDGARError):
    """403 Forbidden — usually missing or invalid User-Agent header."""


class EDGARRateLimitError(EDGARError):
    """429 Too Many Requests — exceeded 10 req/sec limit."""


class EDGARNotFoundError(EDGARError):
    """404 Not Found — CIK or filing does not exist."""
