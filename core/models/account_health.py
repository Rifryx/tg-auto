from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class AccountHealth(Base):
    """Snapshot состояния аккаунта: 1:1 с ``accounts``.

    История инцидентов хранится в ``health_events``. Здесь — только последний
    известный срез: результаты активных проб + агрегированный ``health_score``.
    """

    __tablename__ = "account_health"
    __table_args__ = (
        CheckConstraint(
            "health_score BETWEEN 0 AND 100", name="health_score_range"
        ),
        CheckConstraint(
            "phone_status IN ('unknown', 'ok', 'banned')",
            name="phone_status_allowed",
        ),
    )

    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        primary_key=True,
    )

    health_score: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )
    score_computed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    previous_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    session_alive: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    last_seen_alive_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_session_check_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    spam_blocked: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    spam_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_spam_check_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    phone_status: Mapped[str] = mapped_column(
        String, nullable=False, default="unknown", server_default="unknown"
    )
    last_phone_check_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    has_2fa: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    has_username: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    has_avatar: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    has_bio: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    age_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    last_full_check_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    check_details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
