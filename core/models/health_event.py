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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, CreatedAtMixin


class HealthEvent(Base, CreatedAtMixin):
    __tablename__ = "health_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('flood_wait', 'spam_block', 'restricted', "
            "'proxy_down', 'session_revoked', 'auth_failed')",
            name="event_type_allowed",
        ),
        Index(
            "ix_health_events_account_id_created_at",
            "account_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_health_events_unresolved",
            "resolved",
            postgresql_where=text("resolved = false"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    meta: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    resolved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    triggered_status_change: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
