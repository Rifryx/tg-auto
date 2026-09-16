"""account_health

Snapshot health-состояния аккаунта (1:1 к accounts). Хранит агрегат score,
результаты последних активных проб (session/spam/phone/profile) и служебные
timestamp'ы. История инцидентов остаётся в health_events.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "account_health",
        sa.Column(
            "account_id",
            sa.BigInteger(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "health_score",
            sa.Integer(),
            nullable=False,
            server_default="100",
        ),
        sa.Column("score_computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("previous_score", sa.Integer(), nullable=True),
        sa.Column("session_alive", sa.Boolean(), nullable=True),
        sa.Column("last_seen_alive_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_session_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("spam_blocked", sa.Boolean(), nullable=True),
        sa.Column("spam_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_spam_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "phone_status",
            sa.String(),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("last_phone_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("has_2fa", sa.Boolean(), nullable=True),
        sa.Column("has_username", sa.Boolean(), nullable=True),
        sa.Column("has_avatar", sa.Boolean(), nullable=True),
        sa.Column("has_bio", sa.Boolean(), nullable=True),
        sa.Column("age_days", sa.Integer(), nullable=True),
        sa.Column("last_full_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "check_details",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "health_score BETWEEN 0 AND 100",
            name="ck_account_health_health_score_range",
        ),
        sa.CheckConstraint(
            "phone_status IN ('unknown', 'ok', 'banned')",
            name="ck_account_health_phone_status_allowed",
        ),
    )
    op.create_index(
        "ix_account_health_health_score",
        "account_health",
        ["health_score"],
    )
    op.create_index(
        "ix_account_health_score_computed_at",
        "account_health",
        ["score_computed_at"],
    )

    # Бэкфилл: строка со score=100 для каждого существующего аккаунта. Позволяет
    # использовать INNER JOIN в запросах и не плодить NULL-семантику.
    op.execute(
        "INSERT INTO account_health (account_id) "
        "SELECT id FROM accounts "
        "ON CONFLICT (account_id) DO NOTHING"
    )


def downgrade() -> None:
    op.drop_index("ix_account_health_score_computed_at", table_name="account_health")
    op.drop_index("ix_account_health_health_score", table_name="account_health")
    op.drop_table("account_health")
