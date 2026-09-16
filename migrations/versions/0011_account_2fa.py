"""accounts: колонки под 2FA-пароль (этап 7 УТП)

Добавляет ``two_factor_password_enc`` (шифрованный blob, Fernet, тот же ключ
что и для сессий/прокси) и ``two_factor_hint`` (открытый текст). Пусто на
момент миграции — старые аккаунты 2FA не имели или ставили вручную.

Расширяет CHECK-ограничение ``bulk_jobs.action_type`` под ``set_2fa``.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("two_factor_password_enc", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "accounts", sa.Column("two_factor_hint", sa.String(), nullable=True)
    )

    op.drop_constraint("ck_bulk_jobs_action_type_allowed", "bulk_jobs", type_="check")
    op.create_check_constraint(
        "ck_bulk_jobs_action_type_allowed",
        "bulk_jobs",
        "action_type IN ('set_persona', 'logout_other_sessions', 'set_privacy', "
        "'apply_profile', 'generate_and_apply_profile', 'set_2fa')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_bulk_jobs_action_type_allowed", "bulk_jobs", type_="check")
    op.create_check_constraint(
        "ck_bulk_jobs_action_type_allowed",
        "bulk_jobs",
        "action_type IN ('set_persona', 'logout_other_sessions', 'set_privacy', "
        "'apply_profile', 'generate_and_apply_profile')",
    )
    op.drop_column("accounts", "two_factor_hint")
    op.drop_column("accounts", "two_factor_password_enc")
