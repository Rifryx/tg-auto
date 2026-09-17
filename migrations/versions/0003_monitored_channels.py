"""monitored channels per account

Аккаунт-центричный мониторинг: у каждого аккаунта свой список каналов, которые
он подписывает и комментирует. Таблица в схеме ``commenting``.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monitored_channels",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("input_ref", sa.String(), nullable=False),
        sa.Column("is_folder", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("channel_ref", sa.String(), nullable=True),
        sa.Column("channel_tg_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("discussion_group_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("subscribed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('pending', 'working', 'paused', 'failed')",
            name="monitored_channel_status_allowed",
        ),
        sa.UniqueConstraint("account_id", "input_ref", name="uq_monitored_account_input"),
        schema="commenting",
    )
    op.create_index(
        "ix_monitored_channels_account_id",
        "monitored_channels",
        ["account_id"],
        schema="commenting",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_monitored_channels_account_id", "monitored_channels", schema="commenting"
    )
    op.drop_table("monitored_channels", schema="commenting")
