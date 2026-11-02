"""Переключатель тред-симуляции (аккаунт отвечает сам себе).

С вероятностью 35% (THREAD_CONTINUE_PROB) аккаунт после своего коммента
отвечает сам себе ещё раз — имитация живого треда. Поведение полезное, но
не всегда желаемое (симптом непонятных повторов в логе для пользователя,
который его не ожидал). Новое поле ``thread_simulation_enabled`` даёт
явный выбор; по умолчанию True — поведение не меняется.

Revision ID: 0072
Revises: 0071
Create Date: 2026-11-03
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0072"
down_revision: Union[str, None] = "0071"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column(
            "thread_simulation_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        schema="commenting",
    )


def downgrade() -> None:
    op.drop_column("campaigns", "thread_simulation_enabled", schema="commenting")
