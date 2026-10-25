"""Slow-mode wait limit на кампанию шиллинга.

Если в целевом чате включён slow-mode (ChatSlowModeWaitError), executor
решает: ждать (reschedule через N сек) или пропустить шаг. Порог — это
новое поле ``slow_mode_wait_max_sec``. Default 300 (5 минут) — приближённо
к конкуренту.

Revision ID: 0065
Revises: 0064
Create Date: 2026-10-25
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0065"
down_revision: Union[str, None] = "0064"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column(
            "slow_mode_wait_max_sec",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("300"),
        ),
        schema="shilling",
    )


def downgrade() -> None:
    op.drop_column("campaigns", "slow_mode_wait_max_sec", schema="shilling")
