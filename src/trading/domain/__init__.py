"""Public API for trading.domain. Re-exports commonly-used types.

Keeps imports in application/adapters tidy:
    from trading.domain import Account, Money, Symbol, EventType
"""

from trading.domain.audit.entities import AuditRecord
from trading.domain.common.event_types import (
    AggregateType,
    EventType,
    is_produced_in_v1,
)
from trading.domain.common.events import DomainEvent
from trading.domain.common.value_objects import (
    AccountType,
    ActorId,
    AssetClass,
    BlobKey,
    Chamber,
    CorrelationId,
    DateRange,
    Horizon,
    Money,
    Party,
    Severity,
    SignalKind,
    Symbol,
    TransactionType,
    coerce_symbol,
)
from trading.domain.congressional.entities import (
    Committee,
    FilingId,
    Member,
    MemberId,
    TradeDisclosure,
)
from trading.domain.market_data.entities import Bar, MarketRegime, Quote
from trading.domain.portfolio.entities import (
    Account,
    BrokerAccount,
    DriftKind,
    Position,
)
from trading.domain.signals.entities import Briefing, BriefingId, Signal, SignalId

__all__ = [
    "Account",
    "AccountType",
    "ActorId",
    "AggregateType",
    "AssetClass",
    "AuditRecord",
    "Bar",
    "BlobKey",
    "Briefing",
    "BriefingId",
    "BrokerAccount",
    "Chamber",
    "Committee",
    "CorrelationId",
    "DateRange",
    "DomainEvent",
    "DriftKind",
    "EventType",
    "FilingId",
    "Horizon",
    "MarketRegime",
    "Member",
    "MemberId",
    "Money",
    "Party",
    "Position",
    "Quote",
    "Severity",
    "Signal",
    "SignalId",
    "SignalKind",
    "Symbol",
    "coerce_symbol",
    "TradeDisclosure",
    "TransactionType",
    "is_produced_in_v1",
]
