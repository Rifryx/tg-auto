"""bulk: расширить action_type под оформление профилей (этап 6)

Добавляет ``apply_profile`` и ``generate_and_apply_profile`` в CHECK-ограничение
``bulk_jobs.action_type``. Данных не трогает — только определение constraint'а.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-16
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_bulk_jobs_action_type_allowed", "bulk_jobs", type_="check")
    op.create_check_constraint(
        "ck_bulk_jobs_action_type_allowed",
        "bulk_jobs",
        "action_type IN ('set_persona', 'logout_other_sessions', 'set_privacy', "
        "'apply_profile', 'generate_and_apply_profile')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_bulk_jobs_action_type_allowed", "bulk_jobs", type_="check")
    op.create_check_constraint(
        "ck_bulk_jobs_action_type_allowed",
        "bulk_jobs",
        "action_type IN ('set_persona', 'logout_other_sessions', 'set_privacy')",
    )
