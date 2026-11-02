"""Глубина бэкфилла, макс. слов и возраст постов для комментинга.

Для режима «существующие/сначала старые» добавляем управляемую глубину:
сколько постов вглубь (existing_scope_max_posts) и не старше скольких дней
(existing_scope_max_age_days) — чтобы не комментить тысячу древних постов.
Плюс верхняя граница длины коммента (max_words).

Revision ID: 0069
Revises: 0068
Create Date: 2026-11-02
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0069"
down_revision: Union[str, None] = "0068"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("max_words", sa.Integer(), nullable=True),
        schema="commenting",
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "existing_scope_max_posts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("200"),
        ),
        schema="commenting",
    )
    op.add_column(
        "campaigns",
        sa.Column("existing_scope_max_age_days", sa.Integer(), nullable=True),
        schema="commenting",
    )
    op.create_check_constraint(
        "campaign_max_words_valid",
        "campaigns",
        "max_words IS NULL OR max_words > 0",
        schema="commenting",
    )
    op.create_check_constraint(
        "campaign_existing_scope_max_posts_valid",
        "campaigns",
        "existing_scope_max_posts > 0",
        schema="commenting",
    )
    op.create_check_constraint(
        "campaign_existing_scope_max_age_days_valid",
        "campaigns",
        "existing_scope_max_age_days IS NULL OR existing_scope_max_age_days > 0",
        schema="commenting",
    )


def downgrade() -> None:
    op.drop_constraint(
        "campaign_existing_scope_max_age_days_valid", "campaigns", schema="commenting", type_="check"
    )
    op.drop_constraint(
        "campaign_existing_scope_max_posts_valid", "campaigns", schema="commenting", type_="check"
    )
    op.drop_constraint(
        "campaign_max_words_valid", "campaigns", schema="commenting", type_="check"
    )
    op.drop_column("campaigns", "existing_scope_max_age_days", schema="commenting")
    op.drop_column("campaigns", "existing_scope_max_posts", schema="commenting")
    op.drop_column("campaigns", "max_words", schema="commenting")
