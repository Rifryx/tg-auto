"""Autopilot: goals + actions log (этап 12)

Пользователь ставит цели («держи N аккаунтов в pool»); планировщик читает
цели + текущее состояние (аккаунты, ban_risk) и раздаёт задания через
существующие пути (state machine, task queue). Все решения журналируются
в autopilot_actions для аудита и отображения в UI.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "autopilot_goals",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("goal_type", sa.String(), nullable=False),
        sa.Column(
            "params",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "goal_type IN ('maintain_pool_size', 'keep_low_risk', 'warmup_pipeline')",
            name="goal_type_allowed",
        ),
    )
    op.create_index(
        "ix_autopilot_goals_user_enabled",
        "autopilot_goals",
        ["user_id", "enabled"],
    )

    op.create_table(
        "autopilot_actions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "goal_id",
            sa.BigInteger(),
            sa.ForeignKey("autopilot_goals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column(
            "account_id",
            sa.BigInteger(),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="'planned'"),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column(
            "meta",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "action_type IN ('start_warming', 'retire_risky', 'throttle', 'noop')",
            name="action_type_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'executed', 'failed', 'skipped')",
            name="action_status_allowed",
        ),
    )
    op.create_index(
        "ix_autopilot_actions_goal_created",
        "autopilot_actions",
        ["goal_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_autopilot_actions_goal_created", table_name="autopilot_actions")
    op.drop_table("autopilot_actions")
    op.drop_index("ix_autopilot_goals_user_enabled", table_name="autopilot_goals")
    op.drop_table("autopilot_goals")
