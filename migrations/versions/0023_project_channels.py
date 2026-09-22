"""Учёт каналов, созданных bulk-action'ом create_channel (этап 8, backlog #3).

Каждая строка = один канал, созданный ОТДЕЛЬНЫМ аккаунтом в рамках проекта.
Проект необязателен (можно создать канал вне проекта — тогда project_id NULL).
Уникальность (account_id, channel_tg_id): один аккаунт не создаёт «дубль»
одного и того же канала. При удалении аккаунта — CASCADE удаляем связь;
при удалении проекта — SET NULL (запись остаётся, теряет привязку).

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-22
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_channels",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.BigInteger(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("channel_tg_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_access_hash", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("is_megagroup", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("pinned_message_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("account_id", "channel_tg_id", name="uq_project_channels_acc_tg"),
    )
    op.create_index("ix_project_channels_project", "project_channels", ["project_id"])
    op.create_index("ix_project_channels_account", "project_channels", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_project_channels_account", table_name="project_channels")
    op.drop_index("ix_project_channels_project", table_name="project_channels")
    op.drop_table("project_channels")
