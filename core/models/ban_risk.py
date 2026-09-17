from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class BanRiskSnapshot(Base):
    """Последний прогноз Anti-Ban Predictor для аккаунта (1:1 с accounts)."""

    __tablename__ = "ban_risk_snapshots"
    __table_args__ = (
        CheckConstraint(
            "risk_score BETWEEN 0.0 AND 1.0", name="risk_score_range"
        ),
        CheckConstraint(
            "risk_level IN ('low', 'medium', 'high', 'critical')",
            name="risk_level_allowed",
        ),
    )

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    risk_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )
    risk_level: Mapped[str] = mapped_column(
        String, nullable=False, default="low", server_default="'low'"
    )
    previous_risk_score: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    features: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    contributions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'[]'::jsonb")
    )
    computed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
