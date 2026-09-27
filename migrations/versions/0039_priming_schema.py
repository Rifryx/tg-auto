"""priming: create module schema

Создаёт пустую Postgres-схему ``priming`` для нового модуля Telegram-Прайминг.
Таблицы модуля будут добавлены следующими миграциями (см.
docs/priming-prompts.md, промпты 1.3 и 1.4).

Revision ID: 0039
Revises: 0038
Create Date: 2026-09-27
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0039"
down_revision: Union[str, None] = "0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PRIMING = "priming"


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{PRIMING}"')


def downgrade() -> None:
    op.execute(f'DROP SCHEMA IF EXISTS "{PRIMING}" CASCADE')
