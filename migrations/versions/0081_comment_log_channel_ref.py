"""Нейрокомментинг: канал в логе комментария.

Активность на главном экране показывала «комментарий → КАНАЛ», но канал
определялся по аккаунту (первый monitored-канал), а не по реальному каналу
поста — для аккаунтов с несколькими каналами подпись была неверной
(баг-репорт: «логи как-то своей жизнью живут»). Добавляем явное поле
``channel_ref`` на comment_logs: воркер пишет туда реальный канал поста.

Revision ID: 0081
Revises: 0080
Create Date: 2026-11-13
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0081"
down_revision: Union[str, None] = "0080"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "comment_logs",
        sa.Column("channel_ref", sa.String(), nullable=True),
        schema="commenting",
    )


def downgrade() -> None:
    op.drop_column("comment_logs", "channel_ref", schema="commenting")
