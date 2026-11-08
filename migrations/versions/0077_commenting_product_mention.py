"""Упоминание продукта в комментариях.

С вероятностью product_mention_chance_percent LLM получает инструкцию
органично упомянуть продукт/бренд (и ссылку, если задана) в комментарии.
По умолчанию выключено.

Revision ID: 0077
Revises: 0076
Create Date: 2026-11-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0077"
down_revision: Union[str, None] = "0076"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column(
            "product_mention_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="commenting",
    )
    op.add_column(
        "campaigns",
        sa.Column("product_name", sa.String(), nullable=True),
        schema="commenting",
    )
    op.add_column(
        "campaigns",
        sa.Column("product_url", sa.String(), nullable=True),
        schema="commenting",
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "product_mention_chance_percent",
            sa.Integer(),
            nullable=False,
            server_default="20",
        ),
        schema="commenting",
    )
    op.create_check_constraint(
        "campaign_product_mention_chance_percent_valid",
        "campaigns",
        "product_mention_chance_percent BETWEEN 0 AND 100",
        schema="commenting",
    )


def downgrade() -> None:
    op.drop_constraint(
        "campaign_product_mention_chance_percent_valid",
        "campaigns",
        schema="commenting",
        type_="check",
    )
    op.drop_column("campaigns", "product_mention_chance_percent", schema="commenting")
    op.drop_column("campaigns", "product_url", schema="commenting")
    op.drop_column("campaigns", "product_name", schema="commenting")
    op.drop_column("campaigns", "product_mention_enabled", schema="commenting")
