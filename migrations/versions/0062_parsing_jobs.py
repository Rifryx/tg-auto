"""Задачи парсинга с живым прогрессом и управлением (parsing.jobs).

Чтобы UI показывал реальный ход парсинга (лог, счётчики) и мог ставить на
паузу/останавливать, а не «молча» уходил со страницы.

Revision ID: 0062
Revises: 0061
Create Date: 2026-10-21
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0062"
down_revision: Union[str, None] = "0061"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "parsing"


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("owner_user_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("control", sa.String(), nullable=False, server_default="run"),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "log",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("raw_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inserted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("list_id", sa.BigInteger(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column(
            "meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_parsing_jobs_owner_created",
        "jobs",
        ["owner_user_id", "created_at"],
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_parsing_jobs_owner_created", table_name="jobs", schema=_SCHEMA)
    op.drop_table("jobs", schema=_SCHEMA)
