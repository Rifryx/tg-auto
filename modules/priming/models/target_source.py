"""Источник аудитории для кампании прайминга (spec §4.4).

Одна строка — один прогон парсера (или один ручной импорт). Ссылка на
эту строку живёт в ``campaign_targets.source_id``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import PRIMING_SCHEMA, Base, CreatedAtMixin
from modules.priming.schemas.enums import ParserSourceKind


class PrimingTargetSource(Base, CreatedAtMixin):
    __tablename__ = "target_sources"
    __table_args__ = (
        CheckConstraint(
            "kind IN ("
            + ", ".join(f"'{m.value}'" for m in ParserSourceKind)
            + ")",
            name="kind_allowed",
        ),
        CheckConstraint(
            "raw_count >= 0 AND after_filters_count >= 0 "
            "AND after_filters_count <= raw_count",
            name="counts_valid",
        ),
        CheckConstraint(
            "days_window IS NULL OR days_window > 0",
            name="days_window_valid",
        ),
        CheckConstraint(
            "min_messages IS NULL OR min_messages > 0",
            name="min_messages_valid",
        ),
        {"schema": PRIMING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{PRIMING_SCHEMA}.campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    chat_ref: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    days_window: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    min_messages: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    raw_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    after_filters_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    parsed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
