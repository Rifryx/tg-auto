"""bulk: действия со Stories (этап 9)

Расширяет CHECK-ограничение ``bulk_jobs.action_type`` под ``publish_story`` и
``view_stories``.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-16
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_bulk_jobs_action_type_allowed", "bulk_jobs", type_="check")
    op.create_check_constraint(
        "ck_bulk_jobs_action_type_allowed",
        "bulk_jobs",
        "action_type IN ('set_persona', 'logout_other_sessions', 'set_privacy', "
        "'apply_profile', 'generate_and_apply_profile', 'set_2fa', "
        "'join_channels', 'leave_channels', 'view_channel_posts', "
        "'publish_story', 'view_stories')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_bulk_jobs_action_type_allowed", "bulk_jobs", type_="check")
    op.create_check_constraint(
        "ck_bulk_jobs_action_type_allowed",
        "bulk_jobs",
        "action_type IN ('set_persona', 'logout_other_sessions', 'set_privacy', "
        "'apply_profile', 'generate_and_apply_profile', 'set_2fa', "
        "'join_channels', 'leave_channels', 'view_channel_posts')",
    )
