"""Bulk-action assign_proxy (этап 5, backlog #3).

Расширяет CHECK bulk_jobs.action_type_allowed добавлением 'assign_proxy'.

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-20
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ALLOWED_NEW = (
    "'set_persona', 'logout_other_sessions', 'set_privacy', "
    "'apply_profile', 'generate_and_apply_profile', 'set_2fa', "
    "'join_channels', 'leave_channels', 'view_channel_posts', "
    "'publish_story', 'view_stories', 'assign_proxy'"
)
_ALLOWED_OLD = (
    "'set_persona', 'logout_other_sessions', 'set_privacy', "
    "'apply_profile', 'generate_and_apply_profile', 'set_2fa', "
    "'join_channels', 'leave_channels', 'view_channel_posts', "
    "'publish_story', 'view_stories'"
)


def upgrade() -> None:
    op.drop_constraint("action_type_allowed", "bulk_jobs", type_="check")
    op.create_check_constraint(
        "action_type_allowed",
        "bulk_jobs",
        f"action_type IN ({_ALLOWED_NEW})",
    )


def downgrade() -> None:
    op.drop_constraint("action_type_allowed", "bulk_jobs", type_="check")
    op.create_check_constraint(
        "action_type_allowed",
        "bulk_jobs",
        f"action_type IN ({_ALLOWED_OLD})",
    )
