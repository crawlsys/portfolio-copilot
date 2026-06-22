"""Schwab API response parsers.

Pure functions that convert schwab-py response.json() dicts into
domain types. All parsing logic is isolated here so tests can exercise
it with hand-crafted fixtures.

Response shapes are based on Schwab's Trader API v1 (the schwab-py
library passes through raw responses with minimal wrapping).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from trading.domain import AccountType, AssetClass, Money, Symbol
from trading.domain.market_data.entities import Quote
from trading.domain.portfolio.entities import Account, BrokerAccount, Position


def parse_account_type(type_str: str | None) -> AccountType:
    """Map Schwab accountType string to domain enum."""
    if not type_str:
        return AccountType.UNKNOWN
    mapping = {
        "MARGIN": AccountType.MARGIN,
        "CASH": AccountType.CASH,
        "INDIVIDUAL": AccountType.TAXABLE,
        "JOINT": AccountType.TAXABLE,
        "IRA": AccountType.IRA,
        "ROTH_IRA": AccountType.ROTH_IRA,
        "ROTH": AccountType.ROTH_IRA,
        "TRADITIONAL_IRA": AccountType.IRA,
    }
    return mapping.get(type_str.upper(), AccountType.UNKNOWN)


def parse_broker_account(account_hash: str, account_data: dict[str, Any]) -> BrokerAccount:
    """Parse account metadata into BrokerAccount.

    account_data shape (from get_account or get_accounts):
    {
        "securitiesAccount": {
            "accountNumber": "123456789",
            "type": "MARGIN",
            "currentBalances": {...},
            "positions": [...]
        }
    }
    """
    sec_acct = account_data.get("securitiesAccount", account_data)
    account_number = sec_acct.get("accountNumber", "")
    account_type_str = sec_acct.get("type", "")

    return BrokerAccount(
        account_id=account_hash,
        nickname=_derive_nickname(account_type_str, account_number),
        masked_schwab_id=f"****{account_number[-4:]}"
        if len(account_number) >= 4
        else account_number,
        account_type=parse_account_type(account_type_str),
        margin_enabled=account_type_str.upper() == "MARGIN",
    )


def _derive_nickname(account_type: str, account_number: str) -> str:
    """Generate a human-readable nickname from account type."""
    type_names = {
        "MARGIN": "Margin",
        "CASH": "Cash",
        "INDIVIDUAL": "Individual",
        "JOINT": "Joint",
        "IRA": "IRA",
        "ROTH_IRA": "Roth IRA",
        "ROTH": "Roth IRA",
        "TRADITIONAL_IRA": "Traditional IRA",
    }
    suffix = account_number[-4:] if len(account_number) >= 4 else account_number
    return f"{type_names.get(account_type.upper(), 'Account')} ****{suffix}"


def parse_account(
    account_hash: str, account_data: dict[str, Any], as_of: datetime | None = None
) -> Account:
    """Parse full account snapshot including balances and positions.

    account_data shape:
    {
        "securitiesAccount": {
            "accountNumber": "...",
            "type": "MARGIN",
            "currentBalances": {
                "cashBalance": 50000.00,
                "liquidationValue": 150000.00,
                "buyingPower": 100000.00,
                "marginBalance": -10000.00,
                "dayTradingBuyingPower": 200000.00
            },
            "positions": [...]
        }
    }
    """
    sec_acct = account_data.get("securitiesAccount", account_data)
    balances = sec_acct.get("currentBalances", {})
    raw_positions = sec_acct.get("positions", [])

    cash = _parse_money(balances.get("cashBalance", 0))
    positions = tuple(
        parse_position(account_hash, p) for p in raw_positions if _is_valid_position(p)
    )
    market_value = Money.usd(str(sum(p.market_value.amount for p in positions)))
    net_liq = _parse_money(balances.get("liquidationValue", 0))
    buying_power = _parse_money(balances.get("buyingPower", 0))
    margin_balance = _parse_money_or_none(balances.get("marginBalance"))
    day_pnl = _parse_money_or_none(balances.get("dayPnl"))

    return Account(
        account_id=account_hash,
        cash=cash,
        market_value=market_value,
        net_liquidation=net_liq if net_liq.amount > 0 else cash + market_value,
        buying_power=buying_power,
        margin_balance=margin_balance,
        day_pnl=day_pnl,
        positions=positions,
        as_of=as_of or datetime.now(UTC),
    )


def _is_valid_position(pos_data: dict[str, Any]) -> bool:
    """Filter out invalid positions (e.g., empty symbols, zero quantity)."""
    instrument = pos_data.get("instrument", {})
    symbol = instrument.get("symbol", "")
    quantity = pos_data.get("longQuantity", 0) - pos_data.get("shortQuantity", 0)
    return bool(symbol) and quantity != 0


def parse_position(
    account_id: str, pos_data: dict[str, Any], as_of: datetime | None = None
) -> Position:
    """Parse a single position from Schwab's response.

    pos_data shape:
    {
        "instrument": {
            "symbol": "AAPL",
            "assetType": "EQUITY",
            "cusip": "037833100"
        },
        "longQuantity": 100.0,
        "shortQuantity": 0.0,
        "averagePrice": 150.50,
        "currentDayProfitLoss": 500.00,
        "currentDayProfitLossPercentage": 0.05,
        "marketValue": 17550.00
    }
    """
    instrument = pos_data.get("instrument", {})
    raw_symbol = instrument.get("symbol", "")
    asset_type = instrument.get("assetType", "EQUITY").upper()

    symbol = _parse_symbol(raw_symbol, asset_type)
    long_qty = Decimal(str(pos_data.get("longQuantity", 0)))
    short_qty = Decimal(str(pos_data.get("shortQuantity", 0)))
    quantity = long_qty - short_qty

    avg_price = _parse_money(pos_data.get("averagePrice", 0))
    market_value = _parse_money(pos_data.get("marketValue", 0))
    unrealized_pnl = market_value - (avg_price * abs(quantity))

    return Position(
        account_id=account_id,
        symbol=symbol,
        quantity=quantity,
        average_cost=avg_price,
        market_value=market_value,
        unrealized_pnl=unrealized_pnl,
        as_of=as_of or datetime.now(UTC),
    )


def _parse_symbol(raw_symbol: str, asset_type: str) -> Symbol:
    """Convert Schwab symbol + asset type to domain Symbol."""
    if asset_type == "OPTION":
        return Symbol(raw_symbol, asset_class=AssetClass.OPTION)
    return Symbol(raw_symbol, asset_class=AssetClass.EQUITY)


def parse_quote(symbol: Symbol, quote_data: dict[str, Any], as_of: datetime | None = None) -> Quote:
    """Parse quote data from Schwab's marketdata endpoint.

    quote_data shape (from get_quote or get_quotes):
    {
        "AAPL": {
            "quote": {
                "bidPrice": 174.50,
                "askPrice": 175.50,
                "lastPrice": 175.00,
                "totalVolume": 50000000,
                "quoteTime": 1234567890000
            },
            "reference": {...},
            ...
        }
    }

    Or for single quote it may be unwrapped to just the symbol's data.
    """
    inner = quote_data.get(symbol.ticker, quote_data)

    quote_obj = inner.get("quote", inner)

    bid = _parse_decimal(quote_obj.get("bidPrice", 0))
    ask = _parse_decimal(quote_obj.get("askPrice", 0))
    last = _parse_decimal(quote_obj.get("lastPrice", 0))
    volume = int(quote_obj.get("totalVolume", 0)) if quote_obj.get("totalVolume") else None

    quote_time_ms = quote_obj.get("quoteTime")
    if quote_time_ms and as_of is None:
        as_of = datetime.fromtimestamp(quote_time_ms / 1000, tz=UTC)
    elif as_of is None:
        as_of = datetime.now(UTC)

    return Quote(
        symbol=symbol,
        bid=bid,
        ask=ask,
        last=last if last > 0 else (bid + ask) / 2,
        timestamp=as_of,
        volume=volume,
    )


def _parse_money(value: float | int | str | None) -> Money:
    """Convert numeric value to Money. Handles floats safely."""
    if value is None:
        return Money.zero()
    try:
        dec = _quantize_to_4dp(Decimal(str(value)))
        return Money(amount=dec, currency="USD")
    except (InvalidOperation, ValueError):
        return Money.zero()


def _parse_money_or_none(value: float | int | str | None) -> Money | None:
    """Convert to Money, or None if missing/zero."""
    if value is None:
        return None
    money = _parse_money(value)
    return money if not money.is_zero() else None


def _parse_decimal(value: float | int | str | None) -> Decimal:
    """Convert to Decimal, quantized to 4dp."""
    if value is None:
        return Decimal("0")
    try:
        return _quantize_to_4dp(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _quantize_to_4dp(d: Decimal) -> Decimal:
    """Quantize to 4 decimal places (Money's precision limit)."""
    return d.quantize(Decimal("0.0001"))


__all__ = [
    "parse_account",
    "parse_account_type",
    "parse_broker_account",
    "parse_position",
    "parse_quote",
]
