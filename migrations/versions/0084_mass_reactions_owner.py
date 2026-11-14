"""multi-tenancy: владелец (owner_user_id) у кампаний масс-реакций.

Модуль масс-реакций мёржился отдельной веткой и не попал в 0083 — его кампании
не имели владельца, любой пользователь видел чужие. Добавляем nullable
``owner_user_id`` + индекс и бэкфиллим существующие строки к владельцу из
``LEGACY_OWNER_USER_ID`` (как в 0083); иначе строки остаются «ничьими».

Revision ID: 0084_mass_reactions_owner
Revises: 0083_owner_columns
Create Date: 2026-11-14
"""
from __future__ import annotations

import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0084_mass_reactions_owner"
down_revision: Union[str, None] = "0083_owner_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "mass_reactions"


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("owner_user_id", sa.String(), nullable=True),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_mass_reactions_campaigns_owner_user_id",
        "campaigns",
        ["owner_user_id"],
        schema=_SCHEMA,
    )
    legacy = os.getenv("LEGACY_OWNER_USER_ID")
    if legacy:
        op.execute(
            sa.text(
                f'UPDATE "{_SCHEMA}".campaigns '
                "SET owner_user_id = :owner WHERE owner_user_id IS NULL"
            ).bindparams(owner=legacy)
        )


def downgrade() -> None:
    op.drop_index(
        "ix_mass_reactions_campaigns_owner_user_id",
        table_name="campaigns",
        schema=_SCHEMA,
    )
    op.drop_column("campaigns", "owner_user_id", schema=_SCHEMA)
