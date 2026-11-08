"""Решение капчи (BETA): ИИ отвечает на анти-спам капчу бота обсуждения.

Текстовые и кнопочные капчи — см. modules/commenting/worker/captcha.py.
Картиночные капчи пока не поддержаны (нужен vision-провайдер). По умолчанию
выключено.

Revision ID: 0079
Revises: 0078
Create Date: 2026-11-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0079"
down_revision: Union[str, None] = "0078"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column(
            "captcha_solving_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="commenting",
    )


def downgrade() -> None:
    op.drop_column("campaigns", "captcha_solving_enabled", schema="commenting")
