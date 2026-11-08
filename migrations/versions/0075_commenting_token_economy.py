"""Экономия токенов нейрокомментинга (стаб-пробник перед ИИ-комментом).

Сначала короткая заглушка — и только если она «прошла» (не удалена
ботом/фильтром канала), генерируем и подставляем настоящий ИИ-коммент.
Экономит LLM-токены на заблокированных/мёртвых каналах. По умолчанию
выключено — поведение существующих кампаний не меняется.

Revision ID: 0075
Revises: 0074
Create Date: 2026-11-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0075"
down_revision: Union[str, None] = "0074"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column(
            "token_economy_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="commenting",
    )
    op.add_column(
        "comment_logs",
        sa.Column(
            "is_economy_stub",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="commenting",
    )


def downgrade() -> None:
    op.drop_column("comment_logs", "is_economy_stub", schema="commenting")
    op.drop_column("campaigns", "token_economy_enabled", schema="commenting")
