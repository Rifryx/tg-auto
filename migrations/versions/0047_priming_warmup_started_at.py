"""priming: warmup_started_at on campaign_accounts

Промпт 6.1: линейная рампа дневного лимита от day1 к day7. Чтобы
считать warmup_day, нужно знать, когда конкретный аккаунт начал
работать в кампании (не путать с ``campaign.started_at`` — аккаунт
может присоединиться позже).

Backfill: для существующих строк ставим ``NOW()`` — считаем, что
уже прошедшие ратации всё равно уже случились, а с этого момента
рампа стартует с day1.

Revision ID: 0047
Revises: 0046
Create Date: 2026-09-28
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0047"
down_revision: Union[str, None] = "0046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PRIMING = "priming"


def upgrade() -> None:
    op.add_column(
        "campaign_accounts",
        sa.Column(
            "warmup_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        schema=PRIMING,
    )
    # Бэкфилл: у уже существующих привязок ставим текущий момент —
    # они и так уже работали, рампа стартует с day1 отсюда.
    op.execute(
        f"UPDATE {PRIMING}.campaign_accounts "
        f"SET warmup_started_at = NOW() WHERE warmup_started_at IS NULL"
    )


def downgrade() -> None:
    op.drop_column("campaign_accounts", "warmup_started_at", schema=PRIMING)
