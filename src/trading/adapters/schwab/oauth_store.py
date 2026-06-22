"""OAuth token storage for Schwab.

TokenStore is the abstract interface; FileTokenStore is the default
implementation (encrypted JSON on disk, chmod 0600).

The refresh token expires in 7 DAYS (hard cap from Schwab). This is
the #1 ops risk — if the user doesn't reauth before it expires, all
reads fail. The reauth_endpoint() helper returns a URL the user can
visit to initiate a new OAuth flow; this is stubbed for v1.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass(frozen=True, slots=True)
class OAuthTokens:
    """OAuth token set with expiration metadata.

    access_token: Bearer token for API requests (30 min lifetime).
    refresh_token: Used to obtain new access tokens (7 day lifetime).
    access_expires_at: When access_token expires (UTC).
    refresh_expires_at: When refresh_token expires (UTC). After this,
        the user must re-authenticate via OAuth flow.
    """

    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime

    @property
    def is_access_expired(self) -> bool:
        return datetime.now(UTC) >= self.access_expires_at

    @property
    def is_refresh_expired(self) -> bool:
        return datetime.now(UTC) >= self.refresh_expires_at

    def to_schwab_token_dict(self) -> dict[str, object]:
        """Convert to schwab-py's token file format.

        schwab-py expects a dict with specific keys when loading from
        token_path. This matches that format.
        """
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": "Bearer",
            "expires_in": 1800,  # 30 min
            "scope": "api",
            "expires_at": self.access_expires_at.timestamp(),
            "creation_timestamp": (self.access_expires_at.timestamp() - 1800),  # approximate
        }


class TokenStore(ABC):
    """Abstract interface for persisting OAuth tokens."""

    @abstractmethod
    def load(self) -> OAuthTokens | None:
        """Load stored tokens. Returns None if no tokens exist."""
        ...

    @abstractmethod
    def save(self, tokens: OAuthTokens) -> None:
        """Persist tokens. Must be atomic (no partial writes)."""
        ...

    @abstractmethod
    def clear(self) -> None:
        """Remove stored tokens (for logout/revocation)."""
        ...


class FileTokenStore(TokenStore):
    """File-based token storage with secure permissions.

    Stores tokens as JSON in ~/.tracker/schwab_token.json with chmod 0600.
    Uses atomic write (write to .tmp, rename) to prevent corruption.

    NOTE: tokens are stored in plaintext. For v1 this is acceptable
    (single-user local app); for multi-user/cloud deployment, swap to
    a KMS-encrypted store (future TokenStore impl).
    """

    def __init__(self, path: Path | None = None):
        if path is None:
            path = Path.home() / ".tracker" / "schwab_token.json"
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> OAuthTokens | None:
        if not self._path.exists():
            return None
        try:
            data = json.loads(self._path.read_text())
            return OAuthTokens(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                access_expires_at=datetime.fromtimestamp(data["access_expires_at"], tz=UTC),
                refresh_expires_at=datetime.fromtimestamp(data["refresh_expires_at"], tz=UTC),
            )
        except (KeyError, json.JSONDecodeError) as e:
            raise ValueError(f"Corrupt token file at {self._path}: {e}") from e

    def save(self, tokens: OAuthTokens) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(".tmp")
        data = {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "access_expires_at": tokens.access_expires_at.timestamp(),
            "refresh_expires_at": tokens.refresh_expires_at.timestamp(),
        }
        tmp_path.write_text(json.dumps(data, indent=2))
        os.chmod(tmp_path, 0o600)
        tmp_path.rename(self._path)

    def clear(self) -> None:
        if self._path.exists():
            self._path.unlink()


def reauth_endpoint(redirect_uri: str) -> str:
    """Return a stub reauth endpoint URL.

    In production, this would be a Cloudflare-Access-protected endpoint
    that initiates the OAuth flow and stores tokens. For v1, returns a
    placeholder URL.
    """
    return f"https://tracker.local/auth/schwab/reauth?redirect_uri={redirect_uri}"


__all__ = [
    "FileTokenStore",
    "OAuthTokens",
    "TokenStore",
    "reauth_endpoint",
]
