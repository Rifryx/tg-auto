"""Bulk-action apply_profile_pool (этап 6, backlog #1).

Расширяет CHECK bulk_jobs.action_type_allowed добавлением 'apply_profile_pool'.

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-20
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ALLOWED_NEW = (
    "'set_persona', 'logout_other_sessions', 'set_privacy', "
    "'apply_profile', 'generate_and_apply_profile', 'set_2fa', "
    "'join_channels', 'leave_channels', 'view_channel_posts', "
    "'publish_story', 'view_stories', 'assign_proxy', 'apply_profile_pool'"
)
_ALLOWED_OLD = (
    "'set_persona', 'logout_other_sessions', 'set_privacy', "
    "'apply_profile', 'generate_and_apply_profile', 'set_2fa', "
    "'join_channels', 'leave_channels', 'view_channel_posts', "
    "'publish_story', 'view_stories', 'assign_proxy'"
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
