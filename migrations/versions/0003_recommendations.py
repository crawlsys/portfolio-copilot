"""Add recommendations table.

Revision ID: 0003_recommendations
Revises: 0002_digests
Create Date: 2026-07-01 00:00:00 UTC

The recommendation ledger gives the daily digest LLM memory of its own prior
advice. Each digest run records a structured recommendation (BUY/HOLD) with a
lifecycle (active → acted_on | expired | superseded), a baseline snapshot for
Schwab acted-on detection, and a link to the digest that produced it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_recommendations"
down_revision: str | Sequence[str] | None = "0002_digests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recommendations",
        sa.Column("recommendation_id", sa.String(64), primary_key=True),
        sa.Column("digest_id", sa.String(64), nullable=False),
        sa.Column("digest_date", sa.DateTime(timezone=True), nullable=False),
        # The recommendation itself
        sa.Column("verb", sa.String(16), nullable=False),  # BUY | HOLD
        sa.Column("symbol", sa.String(32)),  # null for HOLD
        sa.Column("amount_usd", sa.Numeric(20, 4)),
        sa.Column("window", sa.String(16), nullable=False),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rationale", sa.Text, nullable=False),
        # Lifecycle: active | acted_on | expired | superseded
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("superseded_by", sa.String(64)),
        sa.Column("acted_on_detail", sa.Text),
        # Baseline snapshot for acted-on detection (captured at issue time)
        sa.Column("baseline_qty", sa.Numeric(20, 8)),
        sa.Column("baseline_cash", sa.Numeric(20, 4)),
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
    op.create_index(
        "ix_recommendations_status_date", "recommendations", ["status", "digest_date"]
    )
    op.create_index("ix_recommendations_symbol", "recommendations", ["symbol"])


def downgrade() -> None:
    op.drop_index("ix_recommendations_symbol", table_name="recommendations")
    op.drop_index("ix_recommendations_status_date", table_name="recommendations")
    op.drop_table("recommendations")
