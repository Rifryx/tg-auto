"""bulk_jobs + bulk_job_items

Инфраструктура массовых операций (этап 5 УТП): очередь заданий вида «применить
действие X к выборке аккаунтов», с прогрессом и per-item статусами.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bulk_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column(
            "payload",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("initiator", sa.String(), nullable=False),
        sa.Column(
            "status", sa.String(), nullable=False, server_default="queued"
        ),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("done_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "action_type IN ('set_persona', 'logout_other_sessions', 'set_privacy')",
            name="ck_bulk_jobs_action_type_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed', 'cancelled')",
            name="ck_bulk_jobs_status_allowed",
        ),
        sa.CheckConstraint("total_count >= 0", name="ck_bulk_jobs_total_count_nonneg"),
        sa.CheckConstraint("done_count >= 0", name="ck_bulk_jobs_done_count_nonneg"),
        sa.CheckConstraint("failed_count >= 0", name="ck_bulk_jobs_failed_count_nonneg"),
        sa.CheckConstraint("skipped_count >= 0", name="ck_bulk_jobs_skipped_count_nonneg"),
    )
    op.create_index("ix_bulk_jobs_status", "bulk_jobs", ["status"])
    op.create_index("ix_bulk_jobs_initiator", "bulk_jobs", ["initiator"])

    op.create_table(
        "bulk_job_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.BigInteger(),
            sa.ForeignKey("bulk_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.BigInteger(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(), nullable=False, server_default="pending"
        ),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("result", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'done', 'failed', 'skipped', 'cancelled')",
            name="ck_bulk_job_items_status_allowed",
        ),
    )
    op.create_index(
        "ix_bulk_job_items_job_id_status", "bulk_job_items", ["job_id", "status"]
    )
    op.create_index("ix_bulk_job_items_account_id", "bulk_job_items", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_bulk_job_items_account_id", table_name="bulk_job_items")
    op.drop_index("ix_bulk_job_items_job_id_status", table_name="bulk_job_items")
    op.drop_table("bulk_job_items")
    op.drop_index("ix_bulk_jobs_initiator", table_name="bulk_jobs")
    op.drop_index("ix_bulk_jobs_status", table_name="bulk_jobs")
    op.drop_table("bulk_jobs")
