"""priming: trigger_actions[] + rotation_strategy

Промпт 5.2: один триггер на кампанию → список триггеров с ротацией.
Executor выбирает конкретный action в момент старта прайминга
(не при постановке в очередь) — можно менять список кампании без
перепланирования уже отправленных job'ов.

Backfill: старое значение trigger_action переезжает в новый массив
одним элементом.

Revision ID: 0046
Revises: 0045
Create Date: 2026-09-28
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0046"
down_revision: Union[str, None] = "0045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PRIMING = "priming"

_ROTATION = ("random", "round_robin", "weighted")


def upgrade() -> None:
    # Массив триггеров и стратегия ротации.
    op.add_column(
        "campaigns",
        sa.Column(
            "trigger_actions",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        schema=PRIMING,
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "trigger_rotation_strategy",
            sa.String(),
            nullable=False,
            server_default="random",
        ),
        schema=PRIMING,
    )
    op.create_check_constraint(
        "ck_campaigns_trigger_rotation_strategy_allowed",
        "campaigns",
        "trigger_rotation_strategy IN ("
        + ", ".join(f"'{v}'" for v in _ROTATION)
        + ")",
        schema=PRIMING,
    )
    # Backfill: переносим старый trigger_action в массив.
    op.execute(f"""
        UPDATE {PRIMING}.campaigns
        SET trigger_actions = to_jsonb(ARRAY[trigger_action])
        WHERE trigger_action IS NOT NULL
    """)
    # Гарантируем, что массив хотя бы с одним элементом.
    op.create_check_constraint(
        "ck_campaigns_trigger_actions_nonempty",
        "campaigns",
        "jsonb_array_length(trigger_actions) >= 1",
        schema=PRIMING,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_campaigns_trigger_actions_nonempty",
        "campaigns", schema=PRIMING,
    )
    op.drop_constraint(
        "ck_campaigns_trigger_rotation_strategy_allowed",
        "campaigns", schema=PRIMING,
    )
    op.drop_column("campaigns", "trigger_rotation_strategy", schema=PRIMING)
    op.drop_column("campaigns", "trigger_actions", schema=PRIMING)
