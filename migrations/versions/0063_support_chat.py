"""Поддержка: тред сообщений пользователь↔менеджер + релеи ответов.

support_messages — сообщения треда (direction: user|manager).
support_relays — связка «сообщение бота в чате менеджера → user_id», чтобы
ответ менеджера реплаем вернулся нужному пользователю.

Revision ID: 0063
Revises: 0062
Create Date: 2026-10-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0063"
down_revision: Union[str, None] = "0062"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "support_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_support_messages_user_created",
        "support_messages",
        ["user_id", "created_at"],
    )
    op.create_table(
        "support_relays",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.String(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_support_relays_chat_msg",
        "support_relays",
        ["chat_id", "message_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_support_relays_chat_msg", table_name="support_relays")
    op.drop_table("support_relays")
    op.drop_index("ix_support_messages_user_created", table_name="support_messages")
    op.drop_table("support_messages")
