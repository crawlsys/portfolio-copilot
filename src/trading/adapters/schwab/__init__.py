"""Schwab broker adapter.

Async BrokerPort implementation wrapping the synchronous schwab-py library.
All API calls are bridged via run_in_executor to keep the event loop free.
"""

from trading.adapters.schwab.broker import SchwabBrokerAdapter
from trading.adapters.schwab.exceptions import (
    SchwabAccountNotFoundError,
    SchwabAuthError,
    SchwabError,
    SchwabRateLimitError,
    SchwabSymbolNotFoundError,
)
from trading.adapters.schwab.oauth_store import (
    FileTokenStore,
    OAuthTokens,
    TokenStore,
    reauth_endpoint,
)
from trading.adapters.schwab.parsing import (
    parse_account,
    parse_account_type,
    parse_broker_account,
    parse_position,
    parse_quote,
)

__all__ = [
    "FileTokenStore",
    "OAuthTokens",
    "SchwabAccountNotFoundError",
    "SchwabAuthError",
    "SchwabBrokerAdapter",
    "SchwabError",
    "SchwabRateLimitError",
    "SchwabSymbolNotFoundError",
    "TokenStore",
    "parse_account",
    "parse_account_type",
    "parse_broker_account",
    "parse_position",
    "parse_quote",
    "reauth_endpoint",
]
