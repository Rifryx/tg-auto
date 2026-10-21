"""Key-value настройки приложения (app_settings): «О приложении», поддержка.

Контент, который раньше был зашит в код и требовал деплоя для изменения, теперь
редактируется из админки и хранится здесь (одна строка на раздел, value JSONB).

Revision ID: 0061
Revises: 0060
Create Date: 2026-10-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0061"
down_revision: Union[str, None] = "0060"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column(
            "value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
