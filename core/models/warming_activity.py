from typing import Any, Optional

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, CreatedAtMixin


class WarmingActivity(Base, CreatedAtMixin):
    __tablename__ = "warming_activities"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('initial', 'maintenance')",
            name="kind_allowed",
        ),
        CheckConstraint(
            "action_type IN ('subscribe_channel', 'read_history', 'reaction', "
            "'view_media', 'join_group', 'idle_online', 'update_profile')",
            name="action_type_allowed",
        ),
        CheckConstraint(
            "status IN ('done', 'failed', 'skipped')",
            name="status_allowed",
        ),
        Index(
            "ix_warming_activities_account_id_created_at",
            "account_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_warming_activities_kind_created_at",
            "kind",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    target: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    meta: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
