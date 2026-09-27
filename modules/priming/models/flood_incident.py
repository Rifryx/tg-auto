"""Отдельный агрегатор FLOOD_WAIT-событий на аккаунт кампании (spec §4.8).

Используется health-монитором и правилом «после N подряд флудвейтов —
карантин»: не хотим сканировать весь ``execution_log`` при каждом тике.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import PRIMING_SCHEMA, Base


class PrimingFloodIncident(Base):
    __tablename__ = "flood_incidents"
    __table_args__ = (
        CheckConstraint(
            "flood_wait_sec > 0",
            name="flood_wait_sec_positive",
        ),
        Index(
            "ix_flood_incidents_campaign_account_at",
            "campaign_account_id", "at",
        ),
        {"schema": PRIMING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    campaign_account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            f"{PRIMING_SCHEMA}.campaign_accounts.id", ondelete="CASCADE"
        ),
        nullable=False,
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    flood_wait_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    endpoint: Mapped[str] = mapped_column(String(128), nullable=False)
