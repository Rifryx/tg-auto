"""Нейрошиллинг: вставка ссылки на продукт в диалог + мониторинг банов за ссылки.

С вероятностью insert_link_chance_percent к message-шагу дописывается ссылка
(brand_link кампании). Если такой пост ловит бан — цель уходит в ЧС с
отдельной причиной и пользователь получает предупреждение. По умолчанию
выключено.

Revision ID: 0080
Revises: 0079
Create Date: 2026-11-13
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0080"
down_revision: Union[str, None] = "0079"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column(
            "insert_link_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="shilling",
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "insert_link_chance_percent",
            sa.Integer(),
            nullable=False,
            server_default="15",
        ),
        schema="shilling",
    )
    op.create_check_constraint(
        "campaign_insert_link_chance_percent_valid",
        "campaigns",
        "insert_link_chance_percent BETWEEN 0 AND 100",
        schema="shilling",
    )


def downgrade() -> None:
    op.drop_constraint(
        "campaign_insert_link_chance_percent_valid",
        "campaigns",
        schema="shilling",
        type_="check",
    )
    op.drop_column("campaigns", "insert_link_chance_percent", schema="shilling")
    op.drop_column("campaigns", "insert_link_enabled", schema="shilling")
