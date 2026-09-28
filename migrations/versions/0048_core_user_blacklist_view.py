"""core: cross-module user blacklist view

Промпт 7.1: единая точка правды по «этого пользователя больше не
трогать». Пока user-level blacklist ведёт только priming — view'ом
UNION'им priming.blacklist в ``core.blacklist_all`` с колонкой
``module``. Когда commenting/shilling заведут свои per-user списки,
добавим их сюда, а вызывающие коды (priming.match, парсер) их
подхватят автоматически.

Revision ID: 0048
Revises: 0047
Create Date: 2026-09-28
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0048"
down_revision: Union[str, None] = "0047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CREATE_SCHEMA_SQL = "CREATE SCHEMA IF NOT EXISTS core"

VIEW_SQL = """
CREATE OR REPLACE VIEW core.blacklist_all AS
SELECT
    'priming'::text AS module,
    id,
    owner_user_id,
    tg_user_id,
    username,
    phone,
    reason,
    created_at AS added_at
FROM priming.blacklist
"""


def upgrade() -> None:
    # Пакет ``core`` в Python не связан с PG-схемой core — она заводится
    # именно сейчас, только под этот view. Другие таблицы core.* пока
    # не планируются.
    op.execute(CREATE_SCHEMA_SQL)
    op.execute(VIEW_SQL)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS core.blacklist_all")
    # Схему не дропаем — вдруг что-то ещё в ней появится.
