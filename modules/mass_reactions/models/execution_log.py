"""Append-only лог попыток поставить реакцию.

Одна строка — одна попытка (реальная или dry-run). Пишется один раз, без
``updated_at``. Индексы — под экран логов (фильтр по outcome + keyset по времени).
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

from core.models.base import MASS_REACTIONS_SCHEMA, Base
from modules.mass_reactions.schemas.enums import ReactionOutcome


class MassReactionLog(Base):
    __tablename__ = "execution_log"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ("
            + ", ".join(f"'{m.value}'" for m in ReactionOutcome)
            + ")",
            name="outcome_allowed",
        ),
        CheckConstraint(
            "latency_ms >= 0",
            name="latency_ms_nonneg",
        ),
        CheckConstraint(
            "flood_wait_sec IS NULL OR flood_wait_sec > 0",
            name="flood_wait_sec_valid",
        ),
        Index("ix_mr_execution_log_campaign_started", "campaign_id", "started_at"),
        Index("ix_mr_execution_log_campaign_outcome", "campaign_id", "outcome"),
        {"schema": MASS_REACTIONS_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{MASS_REACTIONS_SCHEMA}.campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            f"{MASS_REACTIONS_SCHEMA}.campaign_chats.id", ondelete="CASCADE"
        ),
        nullable=False,
    )

    # Сообщение, на которое ставили реакцию (id внутри чата).
    message_tg_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    # Поставленный эмодзи (для успешных реакций).
    emoji: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    outcome: Mapped[str] = mapped_column(String, nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    flood_wait_sec: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    dry_run: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
