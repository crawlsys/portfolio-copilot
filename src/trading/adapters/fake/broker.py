"""FakeBroker — in-memory BrokerPort implementation for tests + local dev.

Default when BROKER_MODE=fake (the v1 default; never touches Schwab).
Seeds with one paper account + a few positions so the dashboard has data
on first run. `apps.cli seed-fake-account` populates this.

Satisfies the full read contract of BrokerPort. When execution eventually
lands, a PaperBroker (a *third* implementation that simulates fills)
joins it — but today there is no write path.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from trading.domain import (
    Account,
    AccountType,
    BrokerAccount,
    Money,
    Position,
    Quote,
    Symbol,
)


class FakeBroker:
    """In-memory broker. Holds accounts, positions, quotes.

    Not a mock — a real implementation that satisfies BrokerPort's read
    contract identically to how SchwabBrokerAdapter will. Tests run
    against this; production runs against Schwab.
    """

    def __init__(self) -> None:
        self._accounts: dict[str, BrokerAccount] = {}
        self._positions: dict[str, dict[str, Position]] = {}
        self._balances: dict[str, dict[str, Money]] = {}
        self._quotes: dict[str, Quote] = {}
        self._orders: dict[str, list[dict[str, object]]] = {}
        self._transactions: dict[str, list[dict[str, object]]] = {}

    # --- Mutation helpers (test/dev only; NOT on the BrokerPort protocol) ----

    def add_account(
        self,
        account_id: str,
        nickname: str,
        masked_schwab_id: str,
        account_type: AccountType = AccountType.TAXABLE,
        margin_enabled: bool = False,
        cash: Money | None = None,
    ) -> BrokerAccount:
        """Register an account with starting cash. Idempotent on account_id.

        Note: no `is_paper` flag. Paper vs live is a wiring concern, not a
        runtime query (per spec + red-team architecture review). The
        BrokerAccount domain type intentionally doesn't carry it; the ORM
        column does, for display only.
        """
        acct = BrokerAccount(
            account_id=account_id,
            nickname=nickname,
            masked_schwab_id=masked_schwab_id,
            account_type=account_type,
            margin_enabled=margin_enabled,
        )
        self._accounts[account_id] = acct
        self._positions.setdefault(account_id, {})
        self._balances[account_id] = {
            "cash": cash or Money.usd("0"),
            "market_value": Money.usd("0"),
            "net_liquidation": cash or Money.usd("0"),
            "buying_power": cash or Money.usd("0"),
        }
        self._orders.setdefault(account_id, [])
        self._transactions.setdefault(account_id, [])
        return acct

    def set_position(
        self,
        account_id: str,
        symbol: Symbol,
        quantity: Decimal,
        average_cost: Money,
        market_value: Money | None = None,
    ) -> Position:
        """Seed or overwrite a position. Recomputes unrealized_pnl."""
        if market_value is None:
            market_value = Money(
                amount=average_cost.amount * quantity, currency=average_cost.currency
            )
        # Quantize to 4dp — Money rejects >4dp, and cost*qty can produce 5+.
        raw_pnl = market_value.amount - (average_cost.amount * quantity)
        pnl = Money(
            amount=raw_pnl.quantize(Decimal("0.0001")),
            currency=average_value_currency(average_cost, market_value),
        )
        pos = Position(
            account_id=account_id,
            symbol=symbol,
            quantity=quantity,
            average_cost=average_cost,
            market_value=market_value,
            unrealized_pnl=pnl,
            as_of=datetime.now(UTC),
        )
        self._positions.setdefault(account_id, {})[symbol.ticker] = pos
        self._recompute_balances(account_id)
        return pos

    def set_quote(
        self,
        symbol: Symbol,
        bid: Decimal,
        ask: Decimal,
        last: Decimal | None = None,
        volume: int | None = None,
    ) -> Quote:
        q = Quote(
            symbol=symbol,
            bid=bid,
            ask=ask,
            last=last if last is not None else (bid + ask) / 2,
            volume=volume,
            timestamp=datetime.now(UTC),
        )
        self._quotes[symbol.ticker] = q
        return q

    # --- BrokerPort read methods ---------------------------------------------

    async def get_accounts(self) -> tuple[BrokerAccount, ...]:
        return tuple(self._accounts.values())

    async def get_account(self, account_id: str) -> Account:
        if account_id not in self._accounts:
            raise KeyError(f"Unknown account: {account_id}")
        b = self._balances[account_id]
        positions = tuple(self._positions[account_id].values())
        return Account(
            account_id=account_id,
            cash=b["cash"],
            market_value=b["market_value"],
            net_liquidation=b["net_liquidation"],
            buying_power=b["buying_power"],
            positions=positions,
            as_of=datetime.now(UTC),
        )

    async def get_positions(self, account_id: str) -> tuple[Position, ...]:
        if account_id not in self._accounts:
            raise KeyError(f"Unknown account: {account_id}")
        return tuple(self._positions[account_id].values())

    async def get_orders(
        self, account_id: str, since: datetime | None = None
    ) -> tuple[dict[str, object], ...]:
        if account_id not in self._accounts:
            raise KeyError(f"Unknown account: {account_id}")
        orders = self._orders[account_id]
        if since is not None:
            orders = [
                o
                for o in orders
                if _as_datetime(o.get("entered_at"), datetime.min.replace(tzinfo=UTC)) >= since
            ]
        return tuple(orders)

    async def get_transactions(
        self, account_id: str, since: datetime | None = None
    ) -> tuple[dict[str, object], ...]:
        if account_id not in self._accounts:
            raise KeyError(f"Unknown account: {account_id}")
        txns = self._transactions[account_id]
        if since is not None:
            txns = [
                t
                for t in txns
                if _as_datetime(t.get("timestamp"), datetime.min.replace(tzinfo=UTC)) >= since
            ]
        return tuple(txns)

    def stream_quotes(self, symbols: tuple[Symbol, ...]) -> AsyncIterator[Quote]:
        """Yield the current quote once per symbol, then end. Sufficient for tests."""
        return self._stream_quotes_impl(symbols)

    async def _stream_quotes_impl(self, symbols: tuple[Symbol, ...]) -> AsyncIterator[Quote]:
        for s in symbols:
            if s.ticker in self._quotes:
                yield self._quotes[s.ticker]
            await asyncio.sleep(0)  # cooperative

    async def get_quote(self, symbol: Symbol) -> Quote:
        if symbol.ticker not in self._quotes:
            raise KeyError(f"No quote for {symbol.ticker}")
        return self._quotes[symbol.ticker]

    # --- Internals -----------------------------------------------------------

    def _recompute_balances(self, account_id: str) -> None:
        positions = self._positions[account_id].values()
        market_value = Money.usd("0")
        for p in positions:
            market_value = market_value + p.market_value
        cash = self._balances[account_id]["cash"]
        self._balances[account_id]["market_value"] = market_value
        self._balances[account_id]["net_liquidation"] = cash + market_value
        self._balances[account_id]["buying_power"] = cash + market_value


def average_value_currency(*monies: Money) -> str:
    """Pick the currency of the first non-zero money; default USD."""
    for m in monies:
        if not m.is_zero():
            return m.currency
    return "USD"


def make_default_fake_broker() -> FakeBroker:
    """Construct a FakeBroker seeded with real positions if available.

    Reads data/holdings.json (produced by scripts/parse_schwab_statement.py)
    if present. Falls back to a small sample account when the JSON is absent
    (CI, fresh checkouts, tests that don't need real data).
    """
    holdings_path = Path(__file__).resolve().parents[4] / "data" / "holdings.json"
    if holdings_path.exists():
        return _broker_from_holdings(holdings_path)
    return _broker_from_sample()


def _broker_from_holdings(path: Path) -> FakeBroker:
    """Build a FakeBroker from a parsed Schwab statement snapshot."""
    snapshot = json.loads(path.read_text())
    broker = FakeBroker()
    account_type = (
        AccountType.MARGIN if "Joint" in snapshot.get("nickname", "") else AccountType.TAXABLE
    )
    broker.add_account(
        account_id=snapshot["account_id"],
        nickname=snapshot.get("nickname", "Schwab"),
        masked_schwab_id=snapshot.get("masked_schwab_id", "****-????"),
        account_type=account_type,
        margin_enabled=True,
        cash=Money.usd(str(snapshot.get("cash", "0"))),
    )
    for h in snapshot.get("holdings", []):
        try:
            sym = Symbol(h["symbol"])
        except ValueError:
            continue  # skip invalid tickers (CUSIPs, preferred-share oddities)
        broker.set_position(
            account_id=snapshot["account_id"],
            symbol=sym,
            quantity=Decimal(str(h["quantity"])),
            average_cost=Money.usd(str(h["cost_basis"])),
            market_value=Money.usd(str(h["market_value"])),
        )
    return broker


def _broker_from_sample() -> FakeBroker:
    """Fallback when no holdings.json exists. Small synthetic account."""
    broker = FakeBroker()
    broker.add_account(
        account_id="paper-001",
        nickname="Paper Taxable",
        masked_schwab_id="****0001",
        account_type=AccountType.MARGIN,
        margin_enabled=True,
        cash=Money.usd("200000"),
    )
    broker.set_position(
        account_id="paper-001",
        symbol=Symbol("AAPL"),
        quantity=Decimal("100"),
        average_cost=Money.usd("150.00"),
        market_value=Money.usd("17500.00"),
    )
    broker.set_position(
        account_id="paper-001",
        symbol=Symbol("NVDA"),
        quantity=Decimal("50"),
        average_cost=Money.usd("400.00"),
        market_value=Money.usd("60000.00"),
    )
    broker.set_quote(Symbol("AAPL"), bid=Decimal("174.50"), ask=Decimal("175.50"))
    broker.set_quote(Symbol("NVDA"), bid=Decimal("1195.00"), ask=Decimal("1205.00"))
    return broker


def _as_datetime(value: object, default: datetime) -> datetime:
    """Coerce a dict value to datetime; return default if not a datetime."""
    return value if isinstance(value, datetime) else default


__all__ = [
    "FakeBroker",
    "make_default_fake_broker",
    "average_value_currency",
]
