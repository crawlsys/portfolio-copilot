"""Initial schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-06-21 00:00:00 UTC

Creates all tables for v1 (portfolio tool, no execution). The event_log
trigger prevents UPDATE/DELETE — that's the durability guarantee.
"""

from __future__ import annotations

from typing import Union
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- Portfolio ---
    op.create_table(
        "broker_accounts",
        sa.Column("account_id", sa.String(64), primary_key=True),
        sa.Column("nickname", sa.String(64), nullable=False),
        sa.Column("masked_schwab_id", sa.String(32), nullable=False),
        sa.Column("account_type", sa.String(32), nullable=False),
        sa.Column("margin_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("allowed_instruments", JSONB, nullable=False, server_default="[]"),
        sa.Column("max_order_size_amount", sa.Numeric(20, 4)),
        sa.Column("max_order_size_currency", sa.String(3), server_default="USD"),
        sa.Column("is_paper", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "positions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.String(64),
            sa.ForeignKey("broker_accounts.account_id"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("asset_class", sa.String(16), nullable=False),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column("average_cost", sa.Numeric(20, 4), nullable=False),
        sa.Column("average_cost_currency", sa.String(3), server_default="USD"),
        sa.Column("market_value", sa.Numeric(20, 4), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(20, 4), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "symbol", name="uq_positions_account_symbol"),
        sa.CheckConstraint("quantity <> 0", name="ck_positions_nonzero_quantity"),
    )

    op.create_table(
        "account_snapshots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("net_liquidation", sa.Numeric(20, 4), nullable=False),
        sa.Column("cash", sa.Numeric(20, 4), nullable=False),
        sa.Column("market_value", sa.Numeric(20, 4), nullable=False),
        sa.Column("buying_power", sa.Numeric(20, 4), nullable=False),
        sa.Column("margin_balance", sa.Numeric(20, 4)),
        sa.Column("day_pnl", sa.Numeric(20, 4)),
        sa.Column("is_paper", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index(
        "ix_account_snapshots_account_as_of",
        "account_snapshots",
        ["account_id", "as_of"],
    )

    # --- Congressional ---
    op.create_table(
        "members",
        sa.Column("member_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("chamber", sa.String(16), nullable=False),
        sa.Column("party", sa.String(32), nullable=False),
        sa.Column("state", sa.String(2)),
        sa.Column("district", sa.String(8)),
        sa.Column("committees", JSONB, nullable=False, server_default="[]"),
        sa.Column("bioguide_id", sa.String(16)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("bioguide_id", name="uq_members_bioguide"),
    )

    op.create_table(
        "trade_disclosures",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("filing_id", sa.String(128), nullable=False),
        sa.Column("member_id", sa.String(64), nullable=False),
        sa.Column("member_name", sa.String(128), nullable=False),
        sa.Column("symbol", sa.String(32)),
        sa.Column("asset_class", sa.String(16)),
        sa.Column("asset_description", sa.Text, nullable=False),
        sa.Column("transaction_type", sa.String(32), nullable=False),
        sa.Column("transaction_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disclosure_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount_range_low", sa.Integer),
        sa.Column("amount_range_high", sa.Integer),
        sa.Column("raw_blob_key", sa.String(256)),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("filing_id", name="uq_disclosures_filing"),
    )
    op.create_index(
        "ix_disclosures_member_date",
        "trade_disclosures",
        ["member_id", "transaction_date"],
    )
    op.create_index(
        "ix_disclosures_symbol_date",
        "trade_disclosures",
        ["symbol", "transaction_date"],
    )
    op.create_index("ix_disclosures_disclosed", "trade_disclosures", ["disclosure_date"])

    # --- Market data cache ---
    op.create_table(
        "quote_cache",
        sa.Column("symbol", sa.String(32), primary_key=True),
        sa.Column("bid", sa.Numeric(20, 4), nullable=False),
        sa.Column("ask", sa.Numeric(20, 4), nullable=False),
        sa.Column("last", sa.Numeric(20, 4), nullable=False),
        sa.Column("volume", sa.BigInteger),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # --- Signals ---
    op.create_table(
        "signals",
        sa.Column("signal_id", sa.String(64), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(32)),
        sa.Column("score", sa.Numeric(8, 4), nullable=False),
        sa.Column("confidence", sa.Numeric(8, 4), nullable=False),
        sa.Column("horizon", sa.String(16), nullable=False),
        sa.Column("thesis", sa.Text, nullable=False),
        sa.Column("features", JSONB, nullable=False, server_default="{}"),
        sa.Column("source_event_ids", JSONB, nullable=False, server_default="[]"),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_signals_kind_observed", "signals", ["kind", "observed_at"])
    op.create_index("ix_signals_symbol", "signals", ["symbol"])

    op.create_table(
        "briefings",
        sa.Column("briefing_id", sa.String(64), primary_key=True),
        sa.Column("briefing_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary_markdown", sa.Text, nullable=False),
        sa.Column("push_excerpt", sa.Text, nullable=False),
        sa.Column("referenced_signal_ids", JSONB, nullable=False, server_default="[]"),
        sa.Column("referenced_disclosure_ids", JSONB, nullable=False, server_default="[]"),
        sa.Column("body_blob_key", sa.String(256)),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_briefings_date", "briefings", ["briefing_date"])

    # --- Audit ---
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("audit_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("actor", sa.String(64)),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("subject_type", sa.String(32), nullable=False),
        sa.Column("subject_id", sa.String(128), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        sa.UniqueConstraint("audit_id", name="uq_audit_id"),
    )
    op.create_index("ix_audit_subject", "audit_log", ["subject_type", "subject_id"])
    op.create_index("ix_audit_correlation", "audit_log", ["correlation_id"])
    op.create_index("ix_audit_occurred", "audit_log", ["occurred_at"])

    # --- Outbox + event log ---
    op.create_table(
        "outbox",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("aggregate_id", sa.String(128), nullable=False),
        sa.Column("aggregate_type", sa.String(32), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("schema_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("envelope", JSONB, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", UUID(as_uuid=True), nullable=False),
        sa.Column("causation_id", UUID(as_uuid=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("locked_by", sa.String(64)),
        sa.Column("last_error", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_outbox_unpublished",
        "outbox",
        ["occurred_at", "id"],
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.create_index(
        "ix_outbox_aggregate",
        "outbox",
        ["aggregate_type", "aggregate_id", "occurred_at"],
    )

    op.create_table(
        "event_log",
        sa.Column("sequence", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("event_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("schema_version", sa.Integer, nullable=False),
        sa.Column("aggregate_id", sa.String(128), nullable=False),
        sa.Column("aggregate_type", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("correlation_id", UUID(as_uuid=True), nullable=False),
        sa.Column("causation_id", UUID(as_uuid=True)),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("envelope", JSONB, nullable=False),
        sa.UniqueConstraint("event_id", name="uq_event_log_event_id"),
    )
    op.create_index("ix_event_log_type_seq", "event_log", ["event_type", "sequence"])
    op.create_index(
        "ix_event_log_aggregate_seq",
        "event_log",
        ["aggregate_type", "aggregate_id", "sequence"],
    )
    op.create_index("ix_event_log_occurred", "event_log", ["occurred_at", "sequence"])

    # The trigger that makes event_log truly append-only. This is the
    # durability guarantee — projections can be rebuilt from this table.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_event_log_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'event_log is append-only';
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER event_log_no_update
        BEFORE UPDATE OR DELETE ON event_log
        FOR EACH ROW EXECUTE FUNCTION prevent_event_log_mutation();
        """
    )

    op.create_table(
        "consumer_offsets",
        sa.Column("consumer_name", sa.String(64), primary_key=True),
        sa.Column("event_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # --- Schwab token state (operational) ---
    op.create_table(
        "schwab_token_state",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("refresh_token_hash", sa.String(128), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_canary_at", sa.DateTime(timezone=True)),
        sa.Column("last_canary_ok", sa.Boolean),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    # Intentionally minimal — downgrades on a money-path system are dangerous.
    # If you need to roll back schema in prod, write a forward migration.
    for table in (
        "schwab_token_state",
        "consumer_offsets",
        "event_log",
        "outbox",
        "audit_log",
        "briefings",
        "signals",
        "quote_cache",
        "trade_disclosures",
        "members",
        "account_snapshots",
        "positions",
        "broker_accounts",
    ):
        op.drop_table(table)
    op.execute("DROP TRIGGER IF EXISTS event_log_no_update ON event_log")
    op.execute("DROP FUNCTION IF EXISTS prevent_event_log_mutation()")
