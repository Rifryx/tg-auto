"""Extraction+ парсера: новые source_kind в parsing.lists.

Было: source_kind ∈ (chat_messages, chat_members, manual_list, upload_csv).
Стало: + channel_commenters (комментаторы из linked-чата канала),
post_reactors (реакторы на посты), list_op (производные списки — пересечение/
вычитание/объединение/сэмпл).

Revision ID: 0052
Revises: 0051
Create Date: 2026-10-05
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0052"
down_revision: Union[str, None] = "0051"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONSTRAINT = "ck_lists_source_kind_allowed"
_OLD = "source_kind IN ('chat_messages', 'chat_members', 'manual_list', 'upload_csv')"
_NEW = (
    "source_kind IN ('chat_messages', 'chat_members', 'manual_list', 'upload_csv', "
    "'channel_commenters', 'post_reactors', 'list_op')"
)


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "lists", schema="parsing", type_="check")
    op.create_check_constraint(_CONSTRAINT, "lists", _NEW, schema="parsing")


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "lists", schema="parsing", type_="check")
    op.create_check_constraint(_CONSTRAINT, "lists", _OLD, schema="parsing")
