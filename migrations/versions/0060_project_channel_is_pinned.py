"""Закрепление канала/чата в диалогах аккаунта (project_channels.is_pinned).

Позволяет из карточки аккаунта закреплять созданный канал/чат в списке диалогов
(ToggleDialogPinRequest). Флаг хранится рядом с остальным состоянием канала.

Revision ID: 0060
Revises: 0059
Create Date: 2026-10-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0060"
down_revision: Union[str, None] = "0059"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "project_channels",
        sa.Column(
            "is_pinned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("project_channels", "is_pinned")
