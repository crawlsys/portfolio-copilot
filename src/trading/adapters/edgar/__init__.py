"""SEC EDGAR adapter — fetches SEC filings (Form 4, 8-K, 13F, etc.)."""

from .client import EDGARClient
from .exceptions import EDGARAuthError, EDGARError, EDGARNotFoundError, EDGARRateLimitError
from .parsing import (
    TRANSACTION_CODES,
    extract_form4_filings,
    normalize_cik,
    parse_form4_xml,
    parse_full_text_search_response,
    parse_ticker_to_cik_map,
    parse_transaction_code,
)

__all__ = [
    "EDGARClient",
    "EDGARError",
    "EDGARAuthError",
    "EDGARRateLimitError",
    "EDGARNotFoundError",
    "TRANSACTION_CODES",
    "normalize_cik",
    "parse_ticker_to_cik_map",
    "extract_form4_filings",
    "parse_form4_xml",
    "parse_full_text_search_response",
    "parse_transaction_code",
]
