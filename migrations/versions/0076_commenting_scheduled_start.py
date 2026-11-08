"""Отложенный запуск кампании (scheduled_start_at).

Пока не наступит это время, on_new_post/on_channel_post молча пропускают
посты — кампания может быть enabled=True и слушатель уже подключён, просто
публикация комментариев откладывается. NULL — без отсрочки (поведение не
меняется).

Revision ID: 0076
Revises: 0075
Create Date: 2026-11-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0076"
down_revision: Union[str, None] = "0075"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("scheduled_start_at", sa.DateTime(timezone=True), nullable=True),
        schema="commenting",
    )


def downgrade() -> None:
    op.drop_column("campaigns", "scheduled_start_at", schema="commenting")
