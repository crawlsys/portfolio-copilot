"""Async Quiver Quant client for congressional trade disclosures."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from datetime import date, timedelta

import httpx

from trading.adapters.quiver.exceptions import (
    QuiverAuthError,
    QuiverError,
    QuiverParseError,
    QuiverRateLimitError,
)
from trading.adapters.quiver.parsing import (
    extract_records,
    parse_member,
    parse_trade_disclosure,
)
from trading.domain import Member, Symbol, TradeDisclosure

_LOGGER = logging.getLogger(__name__)
_PAGE_SIZE = 500


class QuiverClient:
    """Client for Quiver Quant congressional trade disclosure endpoints."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.quiverquant.com",
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def get_recent_disclosures(
        self,
        since: date | None = None,
        limit: int = 100,
    ) -> tuple[TradeDisclosure, ...]:
        """Return Quiver's live congressional trade feed."""

        if limit <= 0:
            return ()
        payload = await self._get_json("/beta/live/congresstrading")
        disclosures = self._parse_disclosures(payload, since=since)
        return disclosures[:limit]

    async def get_disclosures_by_member(
        self,
        member_name: str,
        since: date | None = None,
    ) -> tuple[TradeDisclosure, ...]:
        """Return historical disclosures for a congressional member name."""

        disclosures: list[TradeDisclosure] = []
        page = 1
        while True:
            payload = await self._get_json(
                "/beta/bulk/congresstrading",
                params={
                    "representative": member_name,
                    "page": page,
                    "page_size": _PAGE_SIZE,
                    "nonstock": True,
                    "version": "V2",
                },
            )
            records = extract_records(payload)
            if not records:
                break
            disclosures.extend(self._parse_records(records, since=since))
            if len(records) < _PAGE_SIZE:
                break
            page += 1
        return tuple(disclosures)

    async def get_disclosures_by_symbol(
        self,
        symbol: Symbol,
        since: date | None = None,
    ) -> tuple[TradeDisclosure, ...]:
        """Return historical congressional disclosures involving a ticker."""

        payload = await self._get_json(f"/beta/historical/congresstrading/{symbol.ticker}")
        return self._parse_disclosures(payload, since=since)

    async def get_members(self) -> tuple[Member, ...]:
        """Return Quiver's current active Congress member list."""

        payload = await self._get_json(
            "/beta/live/congress/politicians",
            params={"is_active": True},
        )
        records = extract_records(payload)
        members: list[Member] = []
        for record in records:
            try:
                members.append(parse_member(record))
            except QuiverParseError as exc:
                _LOGGER.warning("Skipping malformed Quiver member record: %s", exc)
        return tuple(members)

    async def backfill(
        self,
        start: date,
        end: date,
    ) -> AsyncIterator[tuple[TradeDisclosure, ...]]:
        """Yield paginated historical disclosure batches over an inclusive date range."""

        if end < start:
            raise ValueError(f"end before start: {end} < {start}")

        current = start
        while current <= end:
            page = 1
            while True:
                payload = await self._get_json(
                    "/beta/bulk/congresstrading",
                    params={
                        "date": current.strftime("%Y%m%d"),
                        "page": page,
                        "page_size": _PAGE_SIZE,
                        "nonstock": True,
                        "version": "V2",
                    },
                )
                records = extract_records(payload)
                if not records:
                    break
                disclosures = tuple(
                    disclosure
                    for disclosure in self._parse_records(records)
                    if start <= disclosure.disclosure_date <= end
                )
                if disclosures:
                    yield disclosures
                if len(records) < _PAGE_SIZE:
                    break
                page += 1
            current += timedelta(days=1)

    async def _get_json(
        self,
        path: str,
        params: Mapping[str, str | int | bool] | None = None,
    ) -> object:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers=headers,
                timeout=self._timeout,
            ) as client:
                response = await client.get(path, params=params)
        except httpx.RequestError as exc:
            msg = f"Quiver request failed: {exc}"
            raise QuiverError(msg) from exc

        self._raise_for_status(response)
        try:
            return response.json()
        except ValueError as exc:
            msg = "Quiver returned malformed JSON"
            raise QuiverError(msg) from exc

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code in {401, 403}:
            msg = f"Quiver authentication failed with HTTP {response.status_code}"
            raise QuiverAuthError(msg)
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            msg = "Quiver rate limit exceeded"
            if retry_after:
                msg = f"{msg}; retry after {retry_after}"
            raise QuiverRateLimitError(msg, retry_after=retry_after)
        if response.status_code >= 500:
            msg = f"Quiver server error HTTP {response.status_code}"
            raise QuiverError(msg)
        if response.status_code >= 400:
            msg = f"Quiver request failed with HTTP {response.status_code}: {response.text}"
            raise QuiverError(msg)

    def _parse_disclosures(
        self,
        payload: object,
        since: date | None = None,
    ) -> tuple[TradeDisclosure, ...]:
        return tuple(self._parse_records(extract_records(payload), since=since))

    def _parse_records(
        self,
        records: tuple[Mapping[str, object], ...],
        since: date | None = None,
    ) -> tuple[TradeDisclosure, ...]:
        disclosures: list[TradeDisclosure] = []
        for record in records:
            try:
                disclosure = parse_trade_disclosure(record)
            except QuiverParseError as exc:
                _LOGGER.warning("Skipping malformed Quiver disclosure record: %s", exc)
                continue
            if since is None or disclosure.disclosure_date >= since:
                disclosures.append(disclosure)
        return tuple(disclosures)
