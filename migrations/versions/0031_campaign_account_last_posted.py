"""campaign_accounts.last_posted_at — для паузы между комментариями (E2.2).

Время последнего коммента аккаунта В РАМКАХ кампании. Раннер помечает его
перед отправкой (под блокировкой строки) и по нему выдерживает
``campaigns.pause_between_sec`` в режиме «по времени после поста».

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-24
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaign_accounts",
        sa.Column("last_posted_at", sa.DateTime(timezone=True), nullable=True),
        schema="commenting",
    )


def downgrade() -> None:
    op.drop_column("campaign_accounts", "last_posted_at", schema="commenting")
