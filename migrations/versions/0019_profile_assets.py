"""Пул asset'ов оформления профиля (этап 6, backlog #1).

Таблица держит пул готовых значений разных типов (аватарки/имена/био/
шаблоны username) для ручного bulk-режима «без LLM». Каждый asset:

* ``kind`` — категория (avatar/first_name/last_name/bio/username_template);
* ``value`` — текст (для не-avatar);
* ``binary`` — байты картинки (для avatar);
* ``mime`` — MIME для avatar;
* ``tags`` JSONB — свободные теги для фильтра;
* ``used_count`` — счётчик применений (для минимальной ротации).

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-20
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "profile_assets",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=True),
        sa.Column("binary", sa.LargeBinary(), nullable=True),
        sa.Column("mime", sa.String(), nullable=True),
        sa.Column(
            "tags",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "used_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "kind IN ('avatar', 'first_name', 'last_name', 'bio', 'username_template')",
            name="profile_asset_kind_allowed",
        ),
        # ровно одно из value/binary заполнено. "binary" — зарезервированное
        # слово Postgres, в сыром SQL CHECK'а обязательно в кавычках.
        sa.CheckConstraint(
            '(value IS NOT NULL) OR ("binary" IS NOT NULL)',
            name="profile_asset_has_content",
        ),
        sa.CheckConstraint(
            'NOT (value IS NOT NULL AND "binary" IS NOT NULL)',
            name="profile_asset_single_content",
        ),
    )
    op.create_index("ix_profile_assets_user_kind", "profile_assets", ["user_id", "kind"])


def downgrade() -> None:
    op.drop_index("ix_profile_assets_user_kind", table_name="profile_assets")
    op.drop_table("profile_assets")
