"""Человекочитаемое название прокси (для навигации/поиска в UI).

proxies.name — опциональная подпись прокси (например «DE-residential-1»),
чтобы отличать и искать прокси в списке, не ориентируясь только на host:port.

Revision ID: 0058
Revises: 0057
Create Date: 2026-10-18
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0058"
down_revision: Union[str, None] = "0057"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("proxies", sa.Column("name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("proxies", "name")
