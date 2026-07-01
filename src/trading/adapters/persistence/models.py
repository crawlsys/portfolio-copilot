"""SQLAlchemy ORM models.

Pragmatic — no repository-interface abstraction over our own DB (per red-team
architecture review). Use SQLAlchemy directly in application services; the
only port-style abstraction here is `UnitOfWork`, which exists to make the
outbox transactional, not to hide SQL.

Decimal precision: NUMERIC(20, 4) for money (handles up to ~$1 trillion to
4 dp; far beyond the user's book). NUMERIC(20, 8) for quantities (options
fractions, crypto splits if ever added).

JSONB for event payloads, signal features, audit metadata.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base for all ORM models. Migration-time DDL lives in Alembic."""


# --- Portfolio ----------------------------------------------------------------


class BrokerAccountRow(Base):
    __tablename__ = "broker_accounts"

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    nickname: Mapped[str] = mapped_column(String(64), nullable=False)
    masked_schwab_id: Mapped[str] = mapped_column(String(32), nullable=False)
    account_type: Mapped[str] = mapped_column(String(32), nullable=False)  # AccountType.name
    margin_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    allowed_instruments: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    max_order_size_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    max_order_size_currency: Mapped[str] = mapped_column(String(3), default="USD")
    is_paper: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    positions: Mapped[list[PositionRow]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class PositionRow(Base):
    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("account_id", "symbol", name="uq_positions_account_symbol"),
        CheckConstraint("quantity <> 0", name="ck_positions_nonzero_quantity"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("broker_accounts.account_id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    asset_class: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    average_cost: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    average_cost_currency: Mapped[str] = mapped_column(String(3), default="USD")
    market_value: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    account: Mapped[BrokerAccountRow] = relationship(back_populates="positions")


class AccountSnapshotRow(Base):
    """Periodic snapshot of account balances — for time-series / charts."""

    __tablename__ = "account_snapshots"
    __table_args__ = (Index("ix_account_snapshots_account_as_of", "account_id", "as_of"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    net_liquidation: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    market_value: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    buying_power: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    margin_balance: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    day_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    is_paper: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


# --- Congressional -----------------------------------------------------------


class MemberRow(Base):
    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("bioguide_id", name="uq_members_bioguide"),)

    member_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    chamber: Mapped[str] = mapped_column(String(16), nullable=False)  # house | senate
    party: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str | None] = mapped_column(String(2))
    district: Mapped[str | None] = mapped_column(String(8))
    committees: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    bioguide_id: Mapped[str | None] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class TradeDisclosureRow(Base):
    """Immutable Congressional trade disclosure. Superseded, never edited."""

    __tablename__ = "trade_disclosures"
    __table_args__ = (
        UniqueConstraint("filing_id", name="uq_disclosures_filing"),
        Index("ix_disclosures_member_date", "member_id", "transaction_date"),
        Index("ix_disclosures_symbol_date", "symbol", "transaction_date"),
        Index("ix_disclosures_disclosed", "disclosure_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    filing_id: Mapped[str] = mapped_column(String(128), nullable=False)
    member_id: Mapped[str] = mapped_column(String(64), nullable=False)
    member_name: Mapped[str] = mapped_column(String(128), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32))
    asset_class: Mapped[str | None] = mapped_column(String(16))
    asset_description: Mapped[str] = mapped_column(Text, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    transaction_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    disclosure_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amount_range_low: Mapped[int | None] = mapped_column(Integer)
    amount_range_high: Mapped[int | None] = mapped_column(Integer)
    raw_blob_key: Mapped[str | None] = mapped_column(String(256))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


# --- Market data (cache) -----------------------------------------------------


class QuoteCacheRow(Base):
    """Latest quote per symbol. Replaced on each poll — not historical."""

    __tablename__ = "quote_cache"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    bid: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    ask: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    last: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    volume: Mapped[int | None] = mapped_column(BigInteger)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


# --- Signals -----------------------------------------------------------------


class SignalRow(Base):
    __tablename__ = "signals"
    __table_args__ = (
        Index("ix_signals_kind_observed", "kind", "observed_at"),
        Index("ix_signals_symbol", "symbol"),
    )

    signal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32))
    score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    horizon: Mapped[str] = mapped_column(String(16), nullable=False)
    thesis: Mapped[str] = mapped_column(Text, nullable=False)
    features: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict, nullable=False)
    source_event_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BriefingRow(Base):
    __tablename__ = "briefings"
    __table_args__ = (Index("ix_briefings_date", "briefing_date"),)

    briefing_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    briefing_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    summary_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    push_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    referenced_signal_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    referenced_disclosure_ids: Mapped[list[str]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    body_blob_key: Mapped[str | None] = mapped_column(String(256))
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


# --- Digest ------------------------------------------------------------------


class DigestRow(Base):
    """Daily digest — a full frontier-model report (portfolio + congressional +
    deployment plan), richer than a briefing. One per date (latest wins)."""

    __tablename__ = "digests"
    __table_args__ = (Index("ix_digests_date", "digest_date"),)

    digest_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    digest_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    summary_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    push_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    net_liquidation: Mapped[str | None] = mapped_column(String(32))
    cash_to_deploy: Mapped[str | None] = mapped_column(String(32))
    disclosures_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    body_blob_key: Mapped[str | None] = mapped_column(String(256))
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class RecommendationRow(Base):
    """One structured recommendation per digest run — the digest LLM's ledger.

    Lifecycle: active → acted_on (Schwab delta detected) | expired (past
    due_date) | superseded (LLM pivoted via `supersedes:`). The baseline
    snapshot (qty/cash at issue time) is what the acted-on detector diffs
    against; the positions table only holds current state.
    """

    __tablename__ = "recommendations"
    __table_args__ = (
        Index("ix_recommendations_status_date", "status", "digest_date"),
        Index("ix_recommendations_symbol", "symbol"),
    )

    recommendation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    digest_id: Mapped[str] = mapped_column(String(64), nullable=False)  # → digests.digest_id
    digest_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # The recommendation itself
    verb: Mapped[str] = mapped_column(String(16), nullable=False)  # BUY | HOLD
    symbol: Mapped[str | None] = mapped_column(String(32))  # null for HOLD
    amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    window: Mapped[str] = mapped_column(String(16), nullable=False)  # this-week|2-3-weeks|...
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)

    # Lifecycle: active | acted_on | expired | superseded
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    superseded_by: Mapped[str | None] = mapped_column(String(64))  # → recommendations
    acted_on_detail: Mapped[str | None] = mapped_column(Text)  # what the detector saw

    # Baseline snapshot for detection (captured at issue time)
    baseline_qty: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    baseline_cash: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


# --- Audit -------------------------------------------------------------------


class AuditRow(Base):
    """Append-only audit trail. Mirror of every event + operator actions."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_subject", "subject_type", "subject_id"),
        Index("ix_audit_correlation", "correlation_id"),
        Index("ix_audit_occurred", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    audit_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    audit_metadata: Mapped[dict[str, str]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )


# --- Event infrastructure (outbox + durable log) -----------------------------


class OutboxRow(Base):
    """Transactional outbox. Rows written in same tx as state changes;
    relay worker publishes them to event_log + bus, marks published_at."""

    __tablename__ = "outbox"
    __table_args__ = (
        Index(
            "ix_outbox_unpublished",
            "occurred_at",
            "id",
            postgresql_where=text("published_at IS NULL"),
        ),
        Index("ix_outbox_aggregate", "aggregate_type", "aggregate_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(pg.UUID(as_uuid=True), primary_key=True)
    aggregate_id: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    envelope: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(pg.UUID(as_uuid=True), nullable=False)
    causation_id: Mapped[UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(64))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class EventLogRow(Base):
    """Append-only durable event log. Source of truth for replay/projection.

    A trigger prevents UPDATE and DELETE — see migration. Replay reads this
    table by sequence; the future backtest harness consumes from here.
    """

    __tablename__ = "event_log"
    __table_args__ = (
        Index("ix_event_log_type_seq", "event_type", "sequence"),
        Index("ix_event_log_aggregate_seq", "aggregate_type", "aggregate_id", "sequence"),
        Index("ix_event_log_occurred", "occurred_at", "sequence"),
    )

    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[UUID] = mapped_column(pg.UUID(as_uuid=True), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    correlation_id: Mapped[UUID] = mapped_column(pg.UUID(as_uuid=True), nullable=False)
    causation_id: Mapped[UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    envelope: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)


class ConsumerOffsetRow(Base):
    """Per-consumer dedup tracking — at-least-once delivery needs idempotent consumers."""

    __tablename__ = "consumer_offsets"

    consumer_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(pg.UUID(as_uuid=True), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


# --- Schwab auth (operational, not domain) -----------------------------------


class SchwabTokenStateRow(Base):
    """Token-expiry ledger. Drives alerts and the staleness indicator in UI."""

    __tablename__ = "schwab_token_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    refresh_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_canary_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_canary_ok: Mapped[bool | None] = mapped_column(Boolean)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
