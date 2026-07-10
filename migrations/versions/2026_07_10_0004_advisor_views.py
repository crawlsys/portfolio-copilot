"""Add advisor_views table.

Revision ID: 0004_advisor_views
Revises: 0003_recommendations
Create Date: 2026-07-10 00:00:00 UTC

Advisor council (adopted from ai-hedge-fund v2): persona LLM analysts form
point-in-time views over fundamentals snapshots. One row per (advisor, model,
snapshot_hash) — simultaneously the LLM cache (unchanged snapshot = no second
call), the audit trail (exact prompts + raw response), and the debug trail
(failed parses persist with abstained=true).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_advisor_views"
down_revision: str | Sequence[str] | None = "0003_recommendations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "advisor_views",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("advisor", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        # The view
        sa.Column("stance", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 2), nullable=False),
        sa.Column("reasoning", sa.Text, nullable=False),
        sa.Column("abstained", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("abstain_reason", sa.Text),
        # Audit trail
        sa.Column("system_prompt", sa.Text, nullable=False),
        sa.Column("user_prompt", sa.Text, nullable=False),
        sa.Column("raw_response", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint(
        "uq_advisor_views_cache_key", "advisor_views", ["advisor", "model", "snapshot_hash"]
    )
    op.create_index(
        "ix_advisor_views_ticker_asof", "advisor_views", ["ticker", "as_of"]
    )


def downgrade() -> None:
    op.drop_index("ix_advisor_views_ticker_asof", table_name="advisor_views")
    op.drop_constraint("uq_advisor_views_cache_key", "advisor_views", type_="unique")
    op.drop_table("advisor_views")
