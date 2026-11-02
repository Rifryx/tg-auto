"""Настраиваемая вероятность стикера/картинки на кампанию комментинга.

Раньше шансы были захардкожены (STICKER_CHANCE=0.25, IMAGE_CHANCE=0.40).
Теперь пользователь задаёт их ползунком — два новых поля в процентах с
дефолтами, равными прежним константам (поведение не меняется, пока не тронут).

Revision ID: 0068
Revises: 0067
Create Date: 2026-11-02
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0068"
down_revision: Union[str, None] = "0067"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column(
            "sticker_chance_percent",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("25"),
        ),
        schema="commenting",
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "image_chance_percent",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("40"),
        ),
        schema="commenting",
    )
    op.create_check_constraint(
        "campaign_sticker_chance_percent_valid",
        "campaigns",
        "sticker_chance_percent BETWEEN 0 AND 100",
        schema="commenting",
    )
    op.create_check_constraint(
        "campaign_image_chance_percent_valid",
        "campaigns",
        "image_chance_percent BETWEEN 0 AND 100",
        schema="commenting",
    )


def downgrade() -> None:
    op.drop_constraint(
        "campaign_image_chance_percent_valid", "campaigns", schema="commenting", type_="check"
    )
    op.drop_constraint(
        "campaign_sticker_chance_percent_valid", "campaigns", schema="commenting", type_="check"
    )
    op.drop_column("campaigns", "image_chance_percent", schema="commenting")
    op.drop_column("campaigns", "sticker_chance_percent", schema="commenting")
