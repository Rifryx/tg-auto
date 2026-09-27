"""Цель кампании прайминга (spec §4.3).

Одна строка = один пользователь-адресат. Не заводит собственных record'ов
пользователя (Telegram user_id, username, phone — храним прямо тут).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import PRIMING_SCHEMA, Base, CreatedAtMixin
from modules.priming.schemas.enums import TargetLastSeen, TargetStatus


class PrimingCampaignTarget(Base, CreatedAtMixin):
    __tablename__ = "campaign_targets"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            + ", ".join(f"'{m.value}'" for m in TargetStatus)
            + ")",
            name="status_allowed",
        ),
        CheckConstraint(
            "last_seen_bucket IN ("
            + ", ".join(f"'{m.value}'" for m in TargetLastSeen)
            + ")",
            name="last_seen_bucket_allowed",
        ),
        CheckConstraint(
            # Не даём завести пустую цель — хотя бы одно поле идентификации
            # должно быть заполнено.
            "tg_user_id IS NOT NULL OR username IS NOT NULL OR phone IS NOT NULL",
            name="identity_present",
        ),
        CheckConstraint(
            "attempts >= 0",
            name="attempts_nonneg",
        ),
        # Быстрая выборка «следующая pending-цель кампании».
        Index(
            "ix_campaign_targets_campaign_status",
            "campaign_id", "status",
        ),
        # Дедуп внутри кампании по tg_user_id (когда он резолвлен).
        Index(
            "ix_campaign_targets_campaign_tg_user",
            "campaign_id", "tg_user_id",
            unique=True,
        ),
        {"schema": PRIMING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{PRIMING_SCHEMA}.campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )

    # FK на priming.target_sources появится в миграции 0041 (промпт 1.4);
    # здесь колонка без FK-констрейнта, чтобы не ссылаться на ещё
    # несуществующую таблицу.
    source_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )

    # ── Идентификация цели ─────────────────────────────────────────────
    tg_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    has_premium: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    last_seen_bucket: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=TargetLastSeen.UNKNOWN.value,
        server_default=TargetLastSeen.UNKNOWN.value,
    )

    # ── Жизненный цикл ─────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=TargetStatus.PENDING.value,
        server_default=TargetStatus.PENDING.value,
    )
    assigned_account_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_error_code: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    primed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
