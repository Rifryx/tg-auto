"""priming: quiet_hours_start/_end window

Разрешаем пользователю задавать окно тихих часов (а не фикс 0–7).
Диапазон по-прежнему интерпретируется как ``[start, end)`` в
локальной TZ цели; start<end.

Revision ID: 0051
Revises: 0050
Create Date: 2026-10-02
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0051"
down_revision: Union[str, None] = "0050"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PRIMING = "priming"


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column(
            "quiet_hours_start",
            sa.SmallInteger(),
            nullable=False,
            server_default="0",
        ),
        schema=PRIMING,
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "quiet_hours_end",
            sa.SmallInteger(),
            nullable=False,
            server_default="7",
        ),
        schema=PRIMING,
    )
    op.create_check_constraint(
        "ck_campaigns_quiet_hours_window_valid",
        "campaigns",
        "quiet_hours_start >= 0 AND quiet_hours_start < 24 "
        "AND quiet_hours_end > quiet_hours_start AND quiet_hours_end <= 24",
        schema=PRIMING,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_campaigns_quiet_hours_window_valid",
        "campaigns", schema=PRIMING, type_="check",
    )
    op.drop_column("campaigns", "quiet_hours_end", schema=PRIMING)
    op.drop_column("campaigns", "quiet_hours_start", schema=PRIMING)
