"""SEC EDGAR API client.

Fetches SEC filings from data.sec.gov. Requires a User-Agent header with
contact email — EDGAR returns 403 without one.

Rate limit: 10 req/sec. Be polite.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import TYPE_CHECKING

import httpx

from .exceptions import EDGARAuthError, EDGARError, EDGARNotFoundError, EDGARRateLimitError
from .parsing import (
    extract_form4_filings,
    normalize_cik,
    parse_form4_xml,
    parse_full_text_search_response,
    parse_ticker_to_cik_map,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

_TICKER_TO_CIK_URL = "https://www.sec.gov/files/company_tickers.json"
_EFTS_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"


class EDGARClient:
    """Async client for SEC EDGAR API.

    Args:
        user_agent: REQUIRED. Format: "AppName email@example.com".
            EDGAR returns 403 without a valid User-Agent identifying the caller.
        base_url: Base URL for data.sec.gov endpoints.
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        user_agent: str,
        *,
        base_url: str = "https://data.sec.gov",
        timeout: float = 30.0,
    ) -> None:
        if not user_agent or "@" not in user_agent:
            raise ValueError(
                "user_agent is required and must contain an email address. "
                "Example: 'tracker admin@example.com'"
            )

        self._user_agent = user_agent
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._ticker_to_cik_cache: dict[str, str] | None = None
        self._cache_lock = asyncio.Lock()

    def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers={"User-Agent": self._user_agent, "Accept": "application/json"},
            timeout=self._timeout,
        )

    async def _request(
        self,
        url: str,
        *,
        accept: str = "application/json",
    ) -> httpx.Response:
        """Make an authenticated request with error handling."""
        async with self._make_client() as client:
            client.headers["Accept"] = accept
            try:
                response = await client.get(url)
            except httpx.TimeoutException as e:
                raise EDGARError(f"Request timed out: {url}") from e
            except httpx.RequestError as e:
                raise EDGARError(f"Request failed: {e}") from e

            if response.status_code == 403:
                raise EDGARAuthError(f"403 Forbidden — check User-Agent header. URL: {url}")
            if response.status_code == 404:
                raise EDGARNotFoundError(f"404 Not Found: {url}")
            if response.status_code == 429:
                raise EDGARRateLimitError(
                    "429 Too Many Requests — exceeded EDGAR rate limit (10 req/sec)"
                )
            if response.status_code >= 500:
                raise EDGARError(f"EDGAR server error {response.status_code}: {url}")

            response.raise_for_status()
            return response

    async def ticker_to_cik(self, ticker: str) -> str:
        """Look up a CIK from a ticker symbol.

        Uses cached company_tickers.json from SEC. Cache is refreshed on first
        call per client instance.

        Raises:
            EDGARNotFoundError: If ticker is not found.
        """
        async with self._cache_lock:
            if self._ticker_to_cik_cache is None:
                response = await self._request(_TICKER_TO_CIK_URL)
                data: Mapping[str, dict[str, object]] = response.json()
                self._ticker_to_cik_cache = parse_ticker_to_cik_map(data)

        ticker_upper = ticker.upper()
        cik = self._ticker_to_cik_cache.get(ticker_upper)
        if cik is None:
            raise EDGARNotFoundError(f"Ticker not found: {ticker}")
        return cik

    async def get_submissions(self, ticker: str) -> dict[str, object]:
        """Get recent filings for a company by ticker.

        Returns the full submissions JSON including company metadata and
        recent filings list.
        """
        cik = await self.ticker_to_cik(ticker)
        url = f"{self._base_url}/submissions/CIK{cik}.json"
        response = await self._request(url)
        result: dict[str, object] = response.json()
        return result

    async def get_form4_filings(
        self,
        ticker: str,
        since: date | None = None,
    ) -> tuple[dict[str, object], ...]:
        """Get Form 4 (insider transaction) filings for a company.

        Args:
            ticker: Stock ticker symbol.
            since: Only return filings on or after this date.

        Returns:
            Tuple of filing metadata dicts with accession_number, filing_date, etc.
        """
        submissions = await self.get_submissions(ticker)
        return extract_form4_filings(submissions, since=since)

    async def get_form4_details(
        self,
        cik: str,
        accession_number: str,
    ) -> dict[str, object] | None:
        """Fetch and parse a specific Form 4 XML document.

        Args:
            cik: Company CIK (will be normalized to 10 digits).
            accession_number: Filing accession number (e.g. "0001140361-26-025622").

        Returns:
            Parsed Form 4 data or None if parsing failed.
        """
        cik_normalized = normalize_cik(cik)
        accession_clean = accession_number.replace("-", "")
        url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik_normalized.lstrip('0')}/"
            f"{accession_clean}/form4.xml"
        )

        response = await self._request(url, accept="application/xml")
        return parse_form4_xml(response.text)

    async def get_13f_holdings(
        self,
        cik: str,
        as_of: date | None = None,
    ) -> dict[str, object]:
        """Get 13F institutional holdings for a filer.

        Note: 13F filers are institutions, not companies. The CIK here is
        the filer's CIK (e.g. Berkshire Hathaway's CIK for their 13F).

        Args:
            cik: Filer CIK.
            as_of: Target quarter-end date (not yet filtered, returns latest).

        Returns:
            Raw submissions JSON for the filer. 13F parsing is complex and
            left to the caller for now.
        """
        cik_normalized = normalize_cik(cik)
        url = f"{self._base_url}/submissions/CIK{cik_normalized}.json"
        response = await self._request(url)
        result = dict(response.json())
        if as_of:
            result["_requested_as_of"] = as_of.isoformat()
        return result

    async def search_full_text(
        self,
        query: str,
        limit: int = 10,
    ) -> tuple[dict[str, object], ...]:
        """Search EDGAR full-text index.

        Searches filing content (not just metadata). Results include
        CIKs, form types, dates, and relevance scores.

        Args:
            query: Search query string.
            limit: Maximum results to return (default 10, max 100).

        Returns:
            Tuple of search result dicts.
        """
        limit = min(limit, 100)
        url = f"{_EFTS_SEARCH_URL}?q={query}&from=0&size={limit}"
        response = await self._request(url)
        data: dict[str, object] = response.json()
        return parse_full_text_search_response(data)
