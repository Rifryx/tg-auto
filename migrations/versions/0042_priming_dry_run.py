"""priming: dry_run флаги для кампаний и лога

Промпт 2.6: добавляет ``priming.campaigns.dry_run`` (флаг «безопасного
прогона» без Telethon-вызовов) и ``priming.execution_log.dry_run``
(пометка, что запись — результат симуляции, не реальный прайм).

Revision ID: 0042
Revises: 0041
Create Date: 2026-09-27
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0042"
down_revision: Union[str, None] = "0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PRIMING = "priming"


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column(
            "dry_run", sa.Boolean(), nullable=False, server_default="false"
        ),
        schema=PRIMING,
    )
    op.add_column(
        "execution_log",
        sa.Column(
            "dry_run", sa.Boolean(), nullable=False, server_default="false"
        ),
        schema=PRIMING,
    )
    # Индекс для UI-фильтра «показать только реальные» — dry_run обычно false.
    op.create_index(
        "ix_execution_log_dry_run",
        "execution_log",
        ["dry_run"],
        postgresql_where=sa.text("dry_run = true"),
        schema=PRIMING,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_execution_log_dry_run",
        table_name="execution_log",
        schema=PRIMING,
    )
    op.drop_column("execution_log", "dry_run", schema=PRIMING)
    op.drop_column("campaigns", "dry_run", schema=PRIMING)
