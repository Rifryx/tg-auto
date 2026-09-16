from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, TimestampMixin


class BulkJob(Base, TimestampMixin):
    """Массовая операция над выборкой аккаунтов (этап 5 УТП).

    Родительская запись: описывает тип действия, общий payload, инициатора и
    агрегированный прогресс. Сами задачи по аккаунтам — в ``bulk_job_items``.
    """

    __tablename__ = "bulk_jobs"
    __table_args__ = (
        CheckConstraint(
            "action_type IN ('set_persona', 'logout_other_sessions', 'set_privacy', "
            "'apply_profile', 'generate_and_apply_profile', 'set_2fa', "
            "'join_channels', 'leave_channels', 'view_channel_posts', "
            "'publish_story', 'view_stories')",
            name="action_type_allowed",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed', 'cancelled')",
            name="status_allowed",
        ),
        CheckConstraint("total_count >= 0", name="total_count_nonneg"),
        CheckConstraint("done_count >= 0", name="done_count_nonneg"),
        CheckConstraint("failed_count >= 0", name="failed_count_nonneg"),
        CheckConstraint("skipped_count >= 0", name="skipped_count_nonneg"),
        Index("ix_bulk_jobs_status", "status"),
        Index("ix_bulk_jobs_initiator", "initiator"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    initiator: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="queued", server_default="queued"
    )

    total_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    done_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    failed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    skipped_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class BulkJobItem(Base):
    """Одна операция над одним аккаунтом в рамках ``BulkJob``."""

    __tablename__ = "bulk_job_items"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'done', 'failed', 'skipped', 'cancelled')",
            name="status_allowed",
        ),
        Index("ix_bulk_job_items_job_id_status", "job_id", "status"),
        Index("ix_bulk_job_items_account_id", "account_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("bulk_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
