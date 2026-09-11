"""add accounts.meta jsonb

Служебная JSONB-колонка для эфемерного состояния аккаунта (например,
``phone_code_hash`` логин-флоу — PROJECT-STAGES §11). Доменные поля сюда не
кладутся, только временные технические данные.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-11
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column(
            "meta",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("accounts", "meta")
