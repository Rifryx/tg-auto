"""Флаг Telegram Premium на аккаунте.

Публикация Stories доступна только с Premium-аккаунтов. Храним флаг, чтобы
показывать бейдж в UI и пропускать не-премиум аккаунты ДО попытки публикации
(иначе — заведомая ошибка PremiumAccountRequiredError). NULL — ещё не знаем.

Revision ID: 0070
Revises: 0069
Create Date: 2026-11-02
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0070"
down_revision: Union[str, None] = "0069"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("is_premium", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("accounts", "is_premium")
