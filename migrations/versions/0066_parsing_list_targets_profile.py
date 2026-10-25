"""Добавить профиль (first_name/last_name/photo_url) к ``parsing.list_targets``.

Парсеры уже вытаскивают first_name/last_name/is_premium при обходе чата —
но на уровне БД имени не хранились, UI не мог их показать (были только
username/phone/user_id). Теперь список спарсенных пользователей выглядит
нормальным списком людей, а не колонкой @логинов.

photo_url NULLABLE: аватарки у Telegram можно получить только через
``download_profile_photo`` (не включено в snapshot — слишком дорого при
парсинге). Поле зарезервировано на будущее. UI пока рендерит инициалы.

Revision ID: 0066
Revises: 0065
Create Date: 2026-10-26
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0066"
down_revision: Union[str, None] = "0065"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "list_targets",
        sa.Column("first_name", sa.String(length=120), nullable=True),
        schema="parsing",
    )
    op.add_column(
        "list_targets",
        sa.Column("last_name", sa.String(length=120), nullable=True),
        schema="parsing",
    )
    op.add_column(
        "list_targets",
        sa.Column("photo_url", sa.String(length=500), nullable=True),
        schema="parsing",
    )


def downgrade() -> None:
    op.drop_column("list_targets", "photo_url", schema="parsing")
    op.drop_column("list_targets", "last_name", schema="parsing")
    op.drop_column("list_targets", "first_name", schema="parsing")
