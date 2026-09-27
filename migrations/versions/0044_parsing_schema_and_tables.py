"""parsing: standalone service (lists + list_targets)

Промпт 3.2b: парсер выносится в отдельный модуль-сервис ``parsing``
рядом с commenting/shilling/priming. Свой schema, свои таблицы:

* ``parsing.lists`` — одна строка = один прогон парсера. Хранит
  метаданные и counters/breakdown.
* ``parsing.list_targets`` — таргеты в этом прогоне; UNIQUE(list_id,
  tg_user_id).

Прайминг больше не пишет парсер-результаты в свою схему — он их
импортирует через ``POST /modules/priming/campaigns/{id}/targets/
import-list`` (следующая миграция/сервис).

Revision ID: 0044
Revises: 0043
Create Date: 2026-09-27
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0044"
down_revision: Union[str, None] = "0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PARSING = "parsing"

_SOURCE_KINDS = ("chat_messages", "chat_members", "manual_list", "upload_csv")
_LAST_SEEN = ("recently", "within_week", "within_month", "long_ago", "unknown")


def _in_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{PARSING}"')

    # ------------------------------------------------------------- lists
    op.create_table(
        "lists",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("owner_user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("source_kind", sa.String(), nullable=False),
        sa.Column("chat_ref", sa.String(), nullable=True),
        sa.Column("days_window", sa.Integer(), nullable=True),
        sa.Column("min_messages", sa.Integer(), nullable=True),
        sa.Column("raw_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("after_filters_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("filters_breakdown", sa.dialects.postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(f"source_kind IN ({_in_sql(_SOURCE_KINDS)})",
                           name="ck_lists_source_kind_allowed"),
        sa.CheckConstraint(
            "raw_count >= 0 AND after_filters_count >= 0 "
            "AND after_filters_count <= raw_count",
            name="ck_lists_counts_valid",
        ),
        schema=PARSING,
    )
    op.create_index(
        "ix_lists_owner_created",
        "lists",
        ["owner_user_id", "created_at"],
        schema=PARSING,
    )

    # ------------------------------------------------------ list_targets
    op.create_table(
        "list_targets",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("list_id", sa.BigInteger(), nullable=False),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("has_premium", sa.Boolean(), nullable=True),
        sa.Column("last_seen_bucket", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["list_id"], [f"{PARSING}.lists.id"],
            name="fk_list_targets_list_id_lists",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "tg_user_id IS NOT NULL OR username IS NOT NULL OR phone IS NOT NULL",
            name="ck_list_targets_identity_present",
        ),
        sa.CheckConstraint(f"last_seen_bucket IN ({_in_sql(_LAST_SEEN)})",
                           name="ck_list_targets_last_seen_bucket_allowed"),
        schema=PARSING,
    )
    # Уникальный индекс: чтобы bulk_create мог делать ON CONFLICT DO NOTHING
    # по (list_id, tg_user_id).
    op.create_index(
        "ix_list_targets_list_tg_user",
        "list_targets",
        ["list_id", "tg_user_id"],
        unique=True,
        schema=PARSING,
    )


def downgrade() -> None:
    op.drop_index("ix_list_targets_list_tg_user", table_name="list_targets", schema=PARSING)
    op.drop_table("list_targets", schema=PARSING)
    op.drop_index("ix_lists_owner_created", table_name="lists", schema=PARSING)
    op.drop_table("lists", schema=PARSING)
    op.execute(f'DROP SCHEMA IF EXISTS "{PARSING}" CASCADE')
