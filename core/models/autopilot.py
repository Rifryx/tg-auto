"""Autopilot: цели пользователя и журнал действий планировщика (этап 12)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class AutopilotGoal(Base):
    """Цель пользователя: что автопилот должен поддерживать."""

    __tablename__ = "autopilot_goals"
    __table_args__ = (
        CheckConstraint(
            "goal_type IN ('maintain_pool_size', 'keep_low_risk', 'warmup_pipeline')",
            name="goal_type_allowed",
        ),
        Index("ix_autopilot_goals_user_enabled", "user_id", "enabled"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    goal_type: Mapped[str] = mapped_column(String, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AutopilotAction(Base):
    """Одна запись в журнале решений/выполнений планировщика."""

    __tablename__ = "autopilot_actions"
    __table_args__ = (
        CheckConstraint(
            "action_type IN ('start_warming', 'retire_risky', 'throttle', 'noop')",
            name="action_type_allowed",
        ),
        CheckConstraint(
            "status IN ('planned', 'executed', 'failed', 'skipped')",
            name="action_status_allowed",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    goal_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("autopilot_goals.id", ondelete="CASCADE"),
        nullable=False,
    )
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    account_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="planned", server_default="'planned'"
    )
    reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
