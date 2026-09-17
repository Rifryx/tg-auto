"""subscriptions

Таблица подписок Mini App: одна строка на user_id (Free тариф — по отсутствию
строки, чтобы таблица не росла для неоплачивающих пользователей).

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-15
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("user_id", sa.String(), primary_key=True, nullable=False),
        sa.Column(
            "plan_id",
            sa.String(),
            nullable=False,
            server_default="free",
        ),
        sa.Column(
            "activated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_method", sa.String(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "plan_id IN ('free', 'pro')", name="ck_subscriptions_plan_id_allowed"
        ),
    )


def downgrade() -> None:
    op.drop_table("subscriptions")
