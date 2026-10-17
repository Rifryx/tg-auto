"""Инвайт-ссылка приватного канала/чата, созданного аккаунтом.

project_channels.invite_link — пригласительная ссылка (t.me/+…) для приватных
каналов; для публичных пусто (у них есть @username).

Revision ID: 0057
Revises: 0056
Create Date: 2026-10-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0057"
down_revision: Union[str, None] = "0056"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "project_channels",
        sa.Column("invite_link", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("project_channels", "invite_link")
