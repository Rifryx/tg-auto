"""Anti-Ban Predictor: таблица ban_risk_snapshots (этап 11)

Хранит последний прогноз риска бана для каждого аккаунта (1:1 с accounts).
Включает risk_score (0.0–1.0), risk_level enum, JSONB features/contributions
для прозрачности и debug, и computed_at для отслеживания свежести.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ban_risk_snapshots",
        sa.Column("account_id", sa.BigInteger(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("risk_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("risk_level", sa.String(), nullable=False, server_default="'low'"),
        sa.Column("previous_risk_score", sa.Float(), nullable=True),
        sa.Column("features", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("contributions", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("risk_score BETWEEN 0.0 AND 1.0", name="risk_score_range"),
        sa.CheckConstraint("risk_level IN ('low', 'medium', 'high', 'critical')", name="risk_level_allowed"),
    )


def downgrade() -> None:
    op.drop_table("ban_risk_snapshots")
