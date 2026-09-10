from typing import Any, Optional

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, CreatedAtMixin


class AccountStatusHistory(Base, CreatedAtMixin):
    __tablename__ = "account_status_history"
    __table_args__ = (
        CheckConstraint(
            "initiator IN ('user', 'auto', 'health')",
            name="initiator_allowed",
        ),
        Index(
            "ix_account_status_history_account_id_created_at",
            "account_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    to_status: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    initiator: Mapped[str] = mapped_column(String, nullable=False)
    meta: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
