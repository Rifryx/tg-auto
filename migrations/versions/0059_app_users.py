"""Профили Telegram-пользователей приложения (для отображения в админке).

app_users — кэш публичного профиля из подписанного initData: username и имя.
Нужен, чтобы в админке показывать пользователей по @username, а не по числовому
user_id. Пишется best-effort при заходе в приложение; источник правды для прав
и подписок остаётся user_id.

Revision ID: 0059
Revises: 0058
Create Date: 2026-10-18
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0059"
down_revision: Union[str, None] = "0058"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_users",
        sa.Column("user_id", sa.String(), primary_key=True),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("first_name", sa.String(), nullable=True),
        sa.Column("last_name", sa.String(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("app_users")
