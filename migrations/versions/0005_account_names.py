"""account first_name / last_name

Редактируемое имя аккаунта (как в Telegram: имя + фамилия). Оба поля
опциональны и применяются к реальному аккаунту воркером (Telethon).

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("first_name", sa.String(), nullable=True))
    op.add_column("accounts", sa.Column("last_name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("accounts", "last_name")
    op.drop_column("accounts", "first_name")
