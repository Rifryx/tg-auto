"""campaign.target_channel nullable

Каналы переехали на аккаунты (аккаунт-центричный мониторинг), кампания стала
просто папкой для группы аккаунтов. Поле ``target_channel`` больше не
обязательно — снимаем NOT NULL.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-14
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "commenting"


def upgrade() -> None:
    op.alter_column(
        "campaigns", "target_channel", nullable=True, schema=_SCHEMA
    )


def downgrade() -> None:
    op.alter_column(
        "campaigns", "target_channel", nullable=False, schema=_SCHEMA
    )
