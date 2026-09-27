"""priming: filters_breakdown в target_sources

Промпт 3.2: колонка JSONB для JSON-разбивки счётчиков отброшенных целей
по причинам фильтра (username / premium / bot / deleted / blacklist).

Revision ID: 0043
Revises: 0042
Create Date: 2026-09-27
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0043"
down_revision: Union[str, None] = "0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PRIMING = "priming"


def upgrade() -> None:
    op.add_column(
        "target_sources",
        sa.Column(
            "filters_breakdown",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema=PRIMING,
    )


def downgrade() -> None:
    op.drop_column("target_sources", "filters_breakdown", schema=PRIMING)
