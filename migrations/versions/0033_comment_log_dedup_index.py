"""Индекс дедупа CommentLog под backfill (E2.1).

Для backfill'а истории канала нужен быстрый чек «этот аккаунт уже
комментировал этот пост»: (account_id, post_channel_msg_id). Без индекса
это seq-scan по всей таблице логов.

Revision ID: 0033
Revises: 0032
Create Date: 2026-09-24
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_comment_logs_account_id_post_channel_msg_id",
        "comment_logs",
        ["account_id", "post_channel_msg_id"],
        schema="commenting",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_comment_logs_account_id_post_channel_msg_id",
        table_name="comment_logs",
        schema="commenting",
    )
