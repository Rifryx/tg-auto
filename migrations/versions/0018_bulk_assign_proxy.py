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
    # HISTORICAL FIX: 0009 создавал constraint с `name="ck_bulk_jobs_action_type_allowed"`,
    # а `Base.metadata` уже имеет naming_convention
    # `ck_%(table_name)s_%(constraint_name)s`. Явное имя тоже подпадает под
    # convention → в Postgres constraint оказывался с двойным префиксом
    # (`ck_bulk_jobs_ck_bulk_jobs_action_type_allowed`). 0010-0013 продолжали
    # дропать/пересоздавать эту же «двойную» форму — работали. А эта миграция
    # использует короткое имя → convention раскрывает в single-`ck_bulk_jobs_...`,
    # которого в БД нет → фатал. Сбрасываем оба возможных имени идемпотентно и
    # пересоздаём коротким именем — дальше 0020/0021/0024 работают корректно.
    op.execute(
        'ALTER TABLE bulk_jobs '
        'DROP CONSTRAINT IF EXISTS ck_bulk_jobs_ck_bulk_jobs_action_type_allowed'
    )
    op.execute(
        'ALTER TABLE bulk_jobs '
        'DROP CONSTRAINT IF EXISTS ck_bulk_jobs_action_type_allowed'
    )
    op.create_check_constraint(
        "action_type_allowed",
        "bulk_jobs",
        f"action_type IN ({_ALLOWED_NEW})",
    )


def downgrade() -> None:
    op.execute(
        'ALTER TABLE bulk_jobs '
        'DROP CONSTRAINT IF EXISTS ck_bulk_jobs_action_type_allowed'
    )
    op.create_check_constraint(
        "action_type_allowed",
        "bulk_jobs",
        f"action_type IN ({_ALLOWED_OLD})",
    )
