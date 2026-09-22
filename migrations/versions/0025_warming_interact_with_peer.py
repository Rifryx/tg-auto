"""Расширение CHECK warming_activities.action_type под interact_with_peer
(этап 10, backlog #2 — trust-graph).

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-22
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ALLOWED_NEW = (
    "'subscribe_channel', 'read_history', 'reaction', "
    "'view_media', 'join_group', 'idle_online', 'update_profile', "
    "'interact_with_peer'"
)
_ALLOWED_OLD = (
    "'subscribe_channel', 'read_history', 'reaction', "
    "'view_media', 'join_group', 'idle_online', 'update_profile'"
)


def upgrade() -> None:
    op.drop_constraint(
        "action_type_allowed", "warming_activities", type_="check"
    )
    op.create_check_constraint(
        "action_type_allowed",
        "warming_activities",
        f"action_type IN ({_ALLOWED_NEW})",
    )


def downgrade() -> None:
    op.drop_constraint(
        "action_type_allowed", "warming_activities", type_="check"
    )
    op.create_check_constraint(
        "action_type_allowed",
        "warming_activities",
        f"action_type IN ({_ALLOWED_OLD})",
    )
