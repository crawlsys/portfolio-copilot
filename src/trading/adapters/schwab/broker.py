"""SchwabBrokerAdapter — async BrokerPort implementation wrapping schwab-py.

schwab-py is synchronous. This adapter bridges to async via run_in_executor.
All heavy lifting (HTTP, auth) happens in the executor; the main loop stays
non-blocking.

OAuth lifecycle:
- Access token: 30 min lifetime, auto-refreshed by schwab-py
- Refresh token: 7 day lifetime (HARD CAP from Schwab)
- If refresh expires, user must re-authenticate via OAuth flow

The client is created lazily in get_client() so the adapter can be
constructed without valid tokens (useful for test fixtures).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import tempfile
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, TypeVar

import httpx
from schwab import auth
from schwab.client import Client as SchwabClientClass

from trading.adapters.schwab.exceptions import (
    SchwabAccountNotFoundError,
    SchwabAuthError,
    SchwabError,
    SchwabRateLimitError,
    SchwabSymbolNotFoundError,
)
from trading.adapters.schwab.oauth_store import FileTokenStore, TokenStore
from trading.adapters.schwab.parsing import (
    parse_account,
    parse_broker_account,
    parse_quote,
)
from trading.domain import Account, BrokerAccount, Position, Quote, Symbol

if TYPE_CHECKING:
    from schwab import Client

T = TypeVar("T")


class SchwabBrokerAdapter:
    """Async BrokerPort implementation using schwab-py.

    Wraps the synchronous schwab-py Client with run_in_executor to
    provide an async interface. Satisfies BrokerPort's read-only contract.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        token_store: TokenStore | None = None,
        executor: ThreadPoolExecutor | None = None,
        token_path: str | None = None,
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        # token_path takes precedence: it's the schwab-py native token file
        # written by the OAuth login flow (and refreshed by schwab-py itself).
        # Falls back to the FileTokenStore abstraction if set.
        self._token_path = token_path
        self._token_store = token_store or (FileTokenStore() if token_path is None else None)
        self._executor = executor or ThreadPoolExecutor(max_workers=4)
        self._client: Client | None = None
        self._account_hashes: dict[str, str] = {}

    async def _run_sync(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Bridge sync schwab-py calls to async via executor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, lambda: func(*args, **kwargs))

    def _get_client(self) -> Client:
        """Lazy-init the schwab Client from the stored token.

        Preferred path: read schwab-py's native token file at ``token_path``
        (written by ``scripts/schwab_login.py`` and refreshed in place by
        schwab-py). Falls back to the FileTokenStore abstraction otherwise.

        Raises SchwabAuthError if no tokens exist or the refresh token
        has expired (7-day hard cap from Schwab).
        """
        if self._client is not None:
            return self._client

        # Preferred: native token file, consumed directly by schwab-py.
        if self._token_path is not None:
            from pathlib import Path  # noqa: PLC0415

            token_file = Path(self._token_path)
            if not token_file.exists():
                raise SchwabAuthError(
                    f"No Schwab token file at {self._token_path}. "
                    "Run scripts/schwab_login.py to authenticate."
                )
            try:
                self._client = auth.client_from_token_file(
                    token_path=self._token_path,
                    api_key=self._client_id,
                    app_secret=self._client_secret,
                    asyncio=False,
                )
            except Exception as e:
                raise SchwabAuthError(f"Failed to create client from token file: {e}") from e
            return self._client

        # Legacy fallback: FileTokenStore (custom format) -> temp file.
        assert self._token_store is not None
        tokens = self._token_store.load()
        if tokens is None:
            raise SchwabAuthError("No OAuth tokens found. Run the OAuth flow to authenticate.")

        if tokens.is_refresh_expired:
            raise SchwabAuthError(
                "Refresh token expired. You must re-authenticate via OAuth flow. "
                f"Token expired at {tokens.refresh_expires_at.isoformat()}"
            )

        token_dict = tokens.to_schwab_token_dict()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(token_dict, f)
            token_path = f.name

        try:
            self._client = auth.client_from_token_file(
                token_path=token_path,
                api_key=self._client_id,
                app_secret=self._client_secret,
                asyncio=False,
            )
        except Exception as e:
            raise SchwabAuthError(f"Failed to create client: {e}") from e

        return self._client

    async def _ensure_account_hashes(self) -> None:
        """Fetch and cache account number -> hash mapping."""
        if self._account_hashes:
            return

        client = self._get_client()
        response: httpx.Response = await self._run_sync(client.get_account_numbers)
        self._check_response(response)

        data = response.json()
        for item in data:
            account_number = item.get("accountNumber", "")
            hash_value = item.get("hashValue", "")
            if hash_value:
                self._account_hashes[hash_value] = account_number

    def _resolve_account_hash(self, account_id: str) -> str:
        """Normalize an account identifier to its Schwab hash.

        Accepts any of:
        - The hash itself (``B1468FC...``) — used internally.
        - The raw account number (``54245456``).
        - A masked id (``5424-5456``) — the human-friendly form used in
          Schwab statements, the dashboard, and the FakeBroker era.

        Raises SchwabAccountNotFoundError if no account matches.
        """
        if account_id in self._account_hashes:
            return account_id

        # Try matching by raw or masked account number.
        normalized = account_id.replace("-", "")
        for hash_value, account_number in self._account_hashes.items():
            if account_number == normalized or account_number == account_id:
                return hash_value
            # Masked form: ****5456 matches an account ending in 5456.
            suffix = account_id.replace("*", "").replace("-", "")
            if len(suffix) >= 4 and account_number.endswith(suffix):
                return hash_value

        raise SchwabAccountNotFoundError(f"Unknown account: {account_id}")

    def _check_response(self, response: httpx.Response) -> None:
        """Check response status and raise appropriate exceptions."""
        if response.status_code == httpx.codes.OK:
            return

        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            retry_after = response.headers.get("Retry-After")
            raise SchwabRateLimitError(
                f"Rate limit exceeded: {response.text}",
                retry_after=int(retry_after) if retry_after else None,
            )

        if response.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
            raise SchwabAuthError(f"Authentication failed: {response.text}")

        if response.status_code == httpx.codes.NOT_FOUND:
            raise SchwabAccountNotFoundError(f"Resource not found: {response.text}")

        raise SchwabError(f"API error {response.status_code}: {response.text}")

    def _get_schwab_client_class(self) -> type[SchwabClientClass]:
        """Return the SchwabClient class for field enums."""
        return SchwabClientClass  # type: ignore[no-any-return]

    # --- BrokerPort methods ---

    async def get_accounts(self) -> tuple[BrokerAccount, ...]:
        """List all linked accounts with metadata."""
        await self._ensure_account_hashes()
        client = self._get_client()

        response: httpx.Response = await self._run_sync(client.get_accounts)
        self._check_response(response)

        data = response.json()
        accounts: list[BrokerAccount] = []

        for account_data in data:
            sec_acct = account_data.get("securitiesAccount", account_data)
            account_number = sec_acct.get("accountNumber", "")

            account_hash = None
            for h, num in self._account_hashes.items():
                if num == account_number:
                    account_hash = h
                    break

            if account_hash:
                accounts.append(parse_broker_account(account_hash, account_data))

        return tuple(accounts)

    async def get_account(self, account_id: str) -> Account:
        """Get full account snapshot with balances and positions."""
        await self._ensure_account_hashes()

        resolved = self._resolve_account_hash(account_id)

        client = self._get_client()
        schwab_client = self._get_schwab_client_class()

        response: httpx.Response = await self._run_sync(
            client.get_account,
            resolved,
            fields=[schwab_client.Account.Fields.POSITIONS],
        )
        self._check_response(response)

        data = response.json()
        return parse_account(resolved, data, as_of=datetime.now(UTC))

    async def get_positions(self, account_id: str) -> tuple[Position, ...]:
        """Get all positions for an account."""
        account = await self.get_account(account_id)
        return account.positions

    async def get_orders(
        self, account_id: str, since: datetime | None = None
    ) -> tuple[dict[str, object], ...]:
        """Get order history. Returns raw dicts (orders not modeled in v1)."""
        await self._ensure_account_hashes()

        resolved = self._resolve_account_hash(account_id)

        client = self._get_client()

        to_dt = datetime.now(UTC)
        from_dt = to_dt - timedelta(days=60) if since is None else since
        if (to_dt - from_dt).days > 60:
            from_dt = to_dt - timedelta(days=60)

        response: httpx.Response = await self._run_sync(
            client.get_orders_for_account,
            resolved,
            from_entered_datetime=from_dt,
            to_entered_datetime=to_dt,
        )
        self._check_response(response)

        data = response.json()
        return tuple(data) if isinstance(data, list) else ()

    async def get_transactions(
        self, account_id: str, since: datetime | None = None
    ) -> tuple[dict[str, object], ...]:
        """Get transaction history. Returns raw dicts."""
        await self._ensure_account_hashes()

        resolved = self._resolve_account_hash(account_id)

        client = self._get_client()

        to_dt = datetime.now(UTC)
        from_dt = to_dt - timedelta(days=60) if since is None else since

        response: httpx.Response = await self._run_sync(
            client.get_transactions,
            resolved,
            start_date=from_dt,
            end_date=to_dt,
        )
        self._check_response(response)

        data = response.json()
        return tuple(data) if isinstance(data, list) else ()

    async def get_quote(self, symbol: Symbol) -> Quote:
        """Get current quote for a symbol."""
        client = self._get_client()
        schwab_client = self._get_schwab_client_class()

        response: httpx.Response = await self._run_sync(
            client.get_quote,
            symbol.ticker,
            fields=[schwab_client.Quote.Fields.QUOTE],
        )

        if response.status_code == httpx.codes.NOT_FOUND:
            raise SchwabSymbolNotFoundError(f"Symbol not found: {symbol.ticker}")

        self._check_response(response)
        data = response.json()
        return parse_quote(symbol, data, as_of=datetime.now(UTC))

    def stream_quotes(self, symbols: tuple[Symbol, ...]) -> AsyncIterator[Quote]:
        """Stream real-time quotes. STUB: yields single snapshot per symbol.

        Real implementation requires schwab-py's streaming client, which
        uses WebSocket. Deferred to post-v1 when real-time becomes needed.
        """
        return self._stream_quotes_impl(symbols)

    async def _stream_quotes_impl(self, symbols: tuple[Symbol, ...]) -> AsyncIterator[Quote]:
        """Stub implementation: poll quotes once per symbol."""
        for sym in symbols:
            with contextlib.suppress(SchwabSymbolNotFoundError):
                yield await self.get_quote(sym)
            await asyncio.sleep(0)

    def close(self) -> None:
        """Clean up resources."""
        self._executor.shutdown(wait=False)
        self._client = None


__all__ = ["SchwabBrokerAdapter"]
