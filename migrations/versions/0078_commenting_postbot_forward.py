"""Пересылка готовых постов из внешнего @PostBot вместо ИИ-комментария.

Аккаунт публикует под постом готовый пост из @PostBot (по id сообщения в
чате аккаунта с ботом) — ИИ-токены не тратятся, промт и фото кампании не
используются. postbot_message_ids — пул id сообщений, выбор случайный.

Revision ID: 0078
Revises: 0077
Create Date: 2026-11-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0078"
down_revision: Union[str, None] = "0077"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column(
            "postbot_forward_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="commenting",
    )
    op.add_column(
        "campaigns",
        sa.Column("postbot_username", sa.String(), nullable=True),
        schema="commenting",
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "postbot_message_ids",
            postgresql.ARRAY(sa.BigInteger()),
            nullable=False,
            server_default="{}",
        ),
        schema="commenting",
    )


def downgrade() -> None:
    op.drop_column("campaigns", "postbot_message_ids", schema="commenting")
    op.drop_column("campaigns", "postbot_username", schema="commenting")
    op.drop_column("campaigns", "postbot_forward_enabled", schema="commenting")
