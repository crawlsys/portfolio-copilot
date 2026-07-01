"""BrokerPort — broker access (reads + agent-driven order placement).

This port exists because we have ≥2 implementations:
- SchwabBrokerAdapter (real, against schwab-py)
- FakeBroker (in-memory, for tests + local dev)

Per red-team architecture review, ports exist only where they earn their
keep. ClockPort and BrokerPort are the two ports; everything else
(Massive, Quiver, EDGAR) is a concrete class.

Order placement is a two-step flow gated by the use case layer:
  preview_order() validates an order spec without submitting — it asks the
  broker "would you accept this?" and returns the projected structure + any
  errors. The PlaceOrder use case shows the preview to the operator, who
  must explicitly confirm before submit_place_order() is called.

Threat model: the LLM agent has code-execution access. Order placement is
intentionally a two-step flow with a hard confirmation gate at the use
case / CLI layer — no single tool call both builds and submits an order.
Every submission is recorded in the append-only audit log.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Protocol, runtime_checkable

from trading.domain import Account, BrokerAccount, Position, Quote, Symbol


@runtime_checkable
class BrokerPort(Protocol):
    """Broker access: reads plus agent-driven order placement.

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
        broker-specific shape, deliberately (we don't model orders here).
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

    async def preview_order(
        self, account_id: str, order_spec: dict[str, object]
    ) -> dict[str, object]:
        """Validate an order spec WITHOUT submitting.

        Asks the broker whether the order would be accepted and returns the
        projected structure plus any errors. Never places the order. The
        PlaceOrder use case shows this to the operator before any submit.
        """
        ...

    async def submit_place_order(
        self, account_id: str, order_spec: dict[str, object]
    ) -> str:
        """Submit a previously-previewed order. Returns the broker order id.

        This is the ONLY method that places a live order. Callers must have
        already called preview_order and obtained operator confirmation.
        """
        ...

    async def cancel_order(self, account_id: str, broker_order_id: str) -> bool:
        """Cancel a working order. Returns True if the cancel was accepted."""
        ...


__all__ = ["BrokerPort"]
