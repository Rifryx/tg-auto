"""priming: quiet_hours_target flag + optional target timezone

Промпт 7.2: не будим цель в её ночь. Кампания включает флаг, TZ берётся
из target'а (если известна) или из fallback-колонки на кампании — иначе
executor пропускает проверку и работает как обычно.

Revision ID: 0049
Revises: 0048
Create Date: 2026-09-28
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: Union[str, None] = "0048"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PRIMING = "priming"


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column(
            "quiet_hours_target",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        schema=PRIMING,
    )
    op.add_column(
        "campaigns",
        sa.Column("quiet_hours_tz", sa.String(length=48), nullable=True),
        schema=PRIMING,
    )


def downgrade() -> None:
    op.drop_column("campaigns", "quiet_hours_tz", schema=PRIMING)
    op.drop_column("campaigns", "quiet_hours_target", schema=PRIMING)
