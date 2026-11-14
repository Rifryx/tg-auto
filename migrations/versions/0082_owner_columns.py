"""multi-tenancy: владелец (user_id) у accounts / personas / proxies.

Эти корневые ресурсы не имели владельца — любой пользователь видел чужие
аккаунты (критично для публичного монетизируемого сервиса). Добавляем
nullable ``user_id`` + индекс и бэкфиллим существующие строки к владельцу из
переменной окружения ``LEGACY_OWNER_USER_ID`` (если задана); иначе строки
остаются «ничьими» и не видны никому.

Revision ID: 0082_owner_columns
Revises: 0081
Create Date: 2026-11-14
"""
from __future__ import annotations

import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0082_owner_columns"
down_revision: Union[str, None] = "0081"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (schema, table, owner_column) — accounts/personas/proxies живут в public и
# получают колонку ``user_id``; кампании шиллинга — в схеме ``shilling`` и
# используют ``owner_user_id`` (как у commenting-кампаний, у которых владелец
# уже есть и отдельной колонки тут не требуется).
_PUBLIC_TABLES = ("accounts", "personas", "proxies")
_SHILLING_SCHEMA = "shilling"


def upgrade() -> None:
    for table in _PUBLIC_TABLES:
        op.add_column(table, sa.Column("user_id", sa.String(), nullable=True))
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])

    op.add_column(
        "campaigns",
        sa.Column("owner_user_id", sa.String(), nullable=True),
        schema=_SHILLING_SCHEMA,
    )
    op.create_index(
        "ix_shilling_campaigns_owner_user_id",
        "campaigns",
        ["owner_user_id"],
        schema=_SHILLING_SCHEMA,
    )

    legacy = os.getenv("LEGACY_OWNER_USER_ID")
    if legacy:
        for table in _PUBLIC_TABLES:
            op.execute(
                sa.text(f"UPDATE {table} SET user_id = :owner WHERE user_id IS NULL")
                .bindparams(owner=legacy)
            )
        # Кампании шиллинга и нейрокомментинга — владелец строкой (owner_user_id).
        op.execute(
            sa.text(
                f'UPDATE "{_SHILLING_SCHEMA}".campaigns '
                "SET owner_user_id = :owner WHERE owner_user_id IS NULL"
            ).bindparams(owner=legacy)
        )
        op.execute(
            sa.text(
                'UPDATE "commenting".campaigns '
                "SET owner_user_id = :owner WHERE owner_user_id IS NULL"
            ).bindparams(owner=legacy)
        )
        # Прайминг хранит владельца как BIGINT created_by — бэкфиллим, только
        # если LEGACY_OWNER_USER_ID численный (Telegram id всегда числовой).
        try:
            legacy_int = int(legacy)
        except (TypeError, ValueError):
            legacy_int = None
        if legacy_int is not None:
            op.execute(
                sa.text(
                    'UPDATE "priming".campaigns '
                    "SET created_by = :owner WHERE created_by IS NULL"
                ).bindparams(owner=legacy_int)
            )


def downgrade() -> None:
    op.drop_index(
        "ix_shilling_campaigns_owner_user_id",
        table_name="campaigns",
        schema=_SHILLING_SCHEMA,
    )
    op.drop_column("campaigns", "owner_user_id", schema=_SHILLING_SCHEMA)
    for table in _PUBLIC_TABLES:
        op.drop_index(f"ix_{table}_user_id", table_name=table)
        op.drop_column(table, "user_id")
