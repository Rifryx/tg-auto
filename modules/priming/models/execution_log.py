"""Append-only лог попыток прайминга (spec §4.7).

Одна строка — один вызов TriggerRunner (промпт 2.1). Без ``updated_at``
и без Update-триггеров: сервисный слой пишет запись один раз в
:class:`ExecutionLogRepository.append` (промпт 1.5) и больше её не трогает.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import PRIMING_SCHEMA, Base
from modules.priming.schemas.enums import ExecutionOutcome, TriggerAction


class PrimingExecutionLog(Base):
    __tablename__ = "execution_log"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ("
            + ", ".join(f"'{m.value}'" for m in ExecutionOutcome)
            + ")",
            name="outcome_allowed",
        ),
        CheckConstraint(
            "trigger_action IN ("
            + ", ".join(f"'{m.value}'" for m in TriggerAction)
            + ")",
            name="trigger_action_allowed",
        ),
        CheckConstraint(
            "latency_ms >= 0",
            name="latency_ms_nonneg",
        ),
        CheckConstraint(
            "flood_wait_sec IS NULL OR flood_wait_sec > 0",
            name="flood_wait_sec_valid",
        ),
        # Экран «Логи» (§7 UI): пилюли-фильтры по outcome + keyset по времени.
        Index("ix_execution_log_campaign_started", "campaign_id", "started_at"),
        Index("ix_execution_log_campaign_outcome", "campaign_id", "outcome"),
        {"schema": PRIMING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{PRIMING_SCHEMA}.campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            f"{PRIMING_SCHEMA}.campaign_targets.id", ondelete="CASCADE"
        ),
        nullable=False,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    outcome: Mapped[str] = mapped_column(String, nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    flood_wait_sec: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    trigger_action: Mapped[str] = mapped_column(String, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
