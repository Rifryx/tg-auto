"""Переключатель подписи к фото-комментарию.

Раньше фото ВСЕГДА шло с подписью (сгенерированным ИИ-текстом). Новое поле
``image_caption_enabled`` (по умолчанию True — поведение не меняется) даёт
выбор: выключить — фото уходит голым, без caption.

Revision ID: 0071
Revises: 0070
Create Date: 2026-11-03
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0071"
down_revision: Union[str, None] = "0070"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column(
            "image_caption_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        schema="commenting",
    )


def downgrade() -> None:
    op.drop_column("campaigns", "image_caption_enabled", schema="commenting")
