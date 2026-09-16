"""personas: поля под Warmup Engine (этап 10)

Добавляет:
* ``interests`` — JSONB-список публичных Telegram username'ов, релевантных
  персоне. Warmup action'ы берут targets отсюда вместо общей константы.
* ``timezone`` — IANA-строка, локальный tz персоны (может быть NULL).
* ``active_hours_start`` / ``active_hours_end`` — локальное окно активности
  (обе колонки NULL → использовать глобальные default'ы).

Пусто на момент миграции: старые персоны сохраняют текущие пресеты — движок
корректно фолбэчит на config.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "personas",
        sa.Column(
            "interests",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("personas", sa.Column("timezone", sa.String(), nullable=True))
    op.add_column("personas", sa.Column("active_hours_start", sa.Time(), nullable=True))
    op.add_column("personas", sa.Column("active_hours_end", sa.Time(), nullable=True))


def downgrade() -> None:
    op.drop_column("personas", "active_hours_end")
    op.drop_column("personas", "active_hours_start")
    op.drop_column("personas", "timezone")
    op.drop_column("personas", "interests")
