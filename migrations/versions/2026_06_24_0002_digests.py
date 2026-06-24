"""Add digests table.

Revision ID: 0002_digests
Revises: 0001_initial_schema
Create Date: 2026-06-24 00:00:00 UTC

A daily digest is a full frontier-model report (portfolio analytics +
congressional signal + a deployment plan), richer than the congressional-only
briefing. Stored one row per generation; the API serves the latest per date.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_digests"
down_revision: str | Sequence[str] | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "digests",
        sa.Column("digest_id", sa.String(64), primary_key=True),
        sa.Column("digest_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary_markdown", sa.Text, nullable=False),
        sa.Column("push_excerpt", sa.Text, nullable=False),
        sa.Column("model", sa.String(128), nullable=False, server_default=""),
        sa.Column("net_liquidation", sa.String(32)),
        sa.Column("cash_to_deploy", sa.String(32)),
        sa.Column("disclosures_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("body_blob_key", sa.String(256)),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_digests_date", "digests", ["digest_date"])


def downgrade() -> None:
    op.drop_index("ix_digests_date", table_name="digests")
    op.drop_table("digests")
