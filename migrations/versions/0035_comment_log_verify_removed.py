"""Verify-after-post: verified_at/removed_at на comment_logs (E4.2).

Оба поля nullable: у логов до фичи и у комментов кампаний с выключенным
``verify_after_post`` — обычно оба NULL.

Revision ID: 0035
Revises: 0034
Create Date: 2026-09-24
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "comment_logs",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        schema="commenting",
    )
    op.add_column(
        "comment_logs",
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        schema="commenting",
    )


def downgrade() -> None:
    op.drop_column("comment_logs", "removed_at", schema="commenting")
    op.drop_column("comment_logs", "verified_at", schema="commenting")
