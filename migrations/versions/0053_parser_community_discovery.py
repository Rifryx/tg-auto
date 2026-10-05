"""Discovery сообществ (этап 2): source_kind community_enrich + таблица
parsing.community_items (обогащённые каналы/чаты).

Revision ID: 0053
Revises: 0052
Create Date: 2026-10-05
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0053"
down_revision: Union[str, None] = "0052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PARSING = "parsing"
_CONSTRAINT = "ck_lists_source_kind_allowed"
_OLD = (
    "source_kind IN ('chat_messages', 'chat_members', 'manual_list', 'upload_csv', "
    "'channel_commenters', 'post_reactors', 'list_op')"
)
_NEW = _OLD[:-1] + ", 'community_enrich')"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "lists", schema=PARSING, type_="check")
    op.create_check_constraint(_CONSTRAINT, "lists", _NEW, schema=PARSING)

    op.create_table(
        "community_items",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("list_id", sa.BigInteger(), nullable=False),
        sa.Column("input_ref", sa.String(), nullable=False),
        sa.Column("channel_tg_id", sa.BigInteger(), nullable=True),
        sa.Column("access_hash", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("kind", sa.String(), nullable=False, server_default="channel"),
        sa.Column("participants_count", sa.Integer(), nullable=True),
        sa.Column("has_linked_chat", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("linked_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("last_post_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_scam", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_fake", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("slowmode_seconds", sa.Integer(), nullable=True),
        sa.Column("about", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["list_id"], [f"{PARSING}.lists.id"],
            name="fk_community_items_list_id_lists",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("kind IN ('channel', 'chat')", name="ck_community_items_kind_allowed"),
        schema=PARSING,
    )
    op.create_index(
        "ix_community_items_list_ref",
        "community_items",
        ["list_id", "input_ref"],
        unique=True,
        schema=PARSING,
    )


def downgrade() -> None:
    op.drop_index("ix_community_items_list_ref", table_name="community_items", schema=PARSING)
    op.drop_table("community_items", schema=PARSING)
    op.drop_constraint(_CONSTRAINT, "lists", schema=PARSING, type_="check")
    op.create_check_constraint(_CONSTRAINT, "lists", _OLD, schema=PARSING)
