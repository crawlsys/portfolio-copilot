"""BrokerPort — read-only broker access in v1.

This port exists because we have ≥2 implementations:
- SchwabBrokerAdapter (real, read-only against schwab-py)
- FakeBroker (in-memory, for tests + local dev)

Per red-team architecture review, ports exist only where they earn their
keep. ClockPort and BrokerPort are the two ports in v1; everything else
(Massive, Quiver, EDGAR) is a concrete class.

The trading methods (place_order, cancel_order) are intentionally NOT in
the v1 protocol. They're referenced in the deferred Execution context
(src/trading/domain/execution/). When that context is activated
(post-backtest validation, see spec §11), the safety apparatus from
spec §10 is added: ExecutableOrder sealed type, separate-process
BrokerSubmitWorker, etc.

Threat model: the LLM agent has code-execution access to the MCP process.
The MCP process must NOT have any path to broker writes. Today that's
trivially true: no write methods exist on this protocol.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Protocol, runtime_checkable

from trading.domain import Account, BrokerAccount, Position, Quote, Symbol


@runtime_checkable
class BrokerPort(Protocol):
    """Read-only broker access. No trading methods in v1.

    Adapters satisfy this contract by shape (structural typing). Implementations:
    - SchwabBrokerAdapter: bridges sync schwab-py to async via run_in_executor.
    - FakeBroker: in-memory; used by tests + when BROKER_MODE=fake.

    All methods are async. The Schwab adapter bridges sync schwab-py calls
    via `loop.run_in_executor` (see SchwabBrokerAdapter._run_sync).
    """

    async def get_accounts(self) -> tuple[BrokerAccount, ...]:
        """List linked accounts with type/margin metadata."""
        ...

    async def get_account(self, account_id: str) -> Account:
        """Single account snapshot — balances + positions."""
        ...

    async def get_positions(self, account_id: str) -> tuple[Position, ...]:
        """Positions for an account, with cost basis + P/L."""
        ...

    async def get_orders(
        self, account_id: str, since: datetime | None = None
    ) -> tuple[dict[str, object], ...]:
        """Order history. Returns raw dicts — the only path where we leak
        broker-specific shape, deliberately (we don't model orders in v1).
        """
        ...

    async def get_transactions(
        self, account_id: str, since: datetime | None = None
    ) -> tuple[dict[str, object], ...]:
        """Transactions (fills, dividends, transfers). Raw dicts, same caveat."""
        ...

    def stream_quotes(self, symbols: tuple[Symbol, ...]) -> AsyncIterator[Quote]:
        """Real-time quote stream. Caller owns iteration lifetime (break to stop).

        AsyncIterator (not AsyncIterable) — single-consumer, caller-controlled.
        """
        ...

    async def get_quote(self, symbol: Symbol) -> Quote:
        """Single quote snapshot. Convenience method."""
        ...

    # --- DEFERRED: trading methods. Uncomment when Execution context is built.
    # See src/trading/domain/execution/__init__.py for the deferral rationale.
    # When activated, also:
    # - Add ExecutableOrder type with sealed-token gate (spec §10)
    # - Run BrokerSubmitWorker in separate k8s Deployment with no MCP path
    # - Apply every money-path red-team fix (idempotency, recovery, retry)
    #
    # async def place_order(self, executable: ExecutableOrder) -> PlaceOrderResult: ...
    # async def cancel_order(self, broker_order_id: BrokerOrderId) -> bool: ...


__all__ = ["BrokerPort"]
