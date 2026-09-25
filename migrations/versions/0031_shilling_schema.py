"""shilling: create module schema

Создаёт пустую Postgres-схему ``shilling`` для нового модуля НейроШиллинг.
Таблицы модуля будут добавлены следующими миграциями (см.
docs/neuroshilling-prompts.md, промпты 1.2 и 1.3).

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-25
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SHILLING = "shilling"


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{SHILLING}"')


def downgrade() -> None:
    op.execute(f'DROP SCHEMA IF EXISTS "{SHILLING}" CASCADE')
