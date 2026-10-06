"""accounts: owner_user_id для per-user изоляции

Пункт 8 чат-бота: добавляем владельца аккаунта, чтобы один пользователь
не мог триггерить аккаунты другого (карантин/возврат из чата). NULL —
«ничей» (legacy-пул до введения владения ИЛИ общий пул): такие аккаунты
из чата может трогать только админ.

Backfill не делаем сознательно — существующие аккаунты остаются NULL
(общий пул). Новые создаются уже с owner_user_id = Telegram user_id
создателя (из initData / require_user).

Revision ID: 0052
Revises: 0051
Create Date: 2026-10-06
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0052"
down_revision: Union[str, None] = "0051"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("owner_user_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_accounts_owner_user_id", "accounts", ["owner_user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_accounts_owner_user_id", table_name="accounts")
    op.drop_column("accounts", "owner_user_id")
