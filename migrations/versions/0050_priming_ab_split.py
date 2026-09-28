"""priming: A/B split на кампании и bucket на аккаунтах

Промпт 7.3: пресеты профилей живут в общем блоке «Аккаунты» и хранятся
там же, но сам факт «A/B теста» — свойство прайминг-кампании: половина
аккаунтов идёт в bucket A, половина в B, метрики бьются по bucket'ам.

Revision ID: 0050
Revises: 0049
Create Date: 2026-09-28
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0050"
down_revision: Union[str, None] = "0049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PRIMING = "priming"


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column(
            "ab_split_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        schema=PRIMING,
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "ab_split_ratio",
            sa.Float(),
            nullable=False,
            server_default="0.5",
        ),
        schema=PRIMING,
    )
    op.create_check_constraint(
        "ck_campaigns_ab_split_ratio_valid",
        "campaigns",
        "ab_split_ratio > 0 AND ab_split_ratio < 1",
        schema=PRIMING,
    )
    op.add_column(
        "campaign_accounts",
        sa.Column("ab_bucket", sa.String(length=1), nullable=True),
        schema=PRIMING,
    )
    op.create_check_constraint(
        "ck_campaign_accounts_ab_bucket_allowed",
        "campaign_accounts",
        "ab_bucket IS NULL OR ab_bucket IN ('a', 'b')",
        schema=PRIMING,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_campaign_accounts_ab_bucket_allowed",
        "campaign_accounts", schema=PRIMING, type_="check",
    )
    op.drop_column("campaign_accounts", "ab_bucket", schema=PRIMING)
    op.drop_constraint(
        "ck_campaigns_ab_split_ratio_valid",
        "campaigns", schema=PRIMING, type_="check",
    )
    op.drop_column("campaigns", "ab_split_ratio", schema=PRIMING)
    op.drop_column("campaigns", "ab_split_enabled", schema=PRIMING)
