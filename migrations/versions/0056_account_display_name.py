"""Произвольное отображаемое имя аккаунта (номер/username/своё).

accounts.display_name — опциональная подпись для отображения аккаунта в UI
вместо замаскированного номера. Пусто → показываем номер.

Revision ID: 0056
Revises: 0055
Create Date: 2026-10-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0056"
down_revision: Union[str, None] = "0055"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("display_name", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("accounts", "display_name")
