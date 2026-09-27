"""ORM для parsing.list_targets (промпт 3.2b)."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, ForeignKey, Index, String,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import PARSING_SCHEMA, Base, CreatedAtMixin


_LAST_SEEN_SQL = (
    "last_seen_bucket IN ('recently', 'within_week', 'within_month', "
    "'long_ago', 'unknown')"
)


class ParsedListTarget(Base, CreatedAtMixin):
    __tablename__ = "list_targets"
    __table_args__ = (
        CheckConstraint(
            "tg_user_id IS NOT NULL OR username IS NOT NULL OR phone IS NOT NULL",
            name="identity_present",
        ),
        CheckConstraint(_LAST_SEEN_SQL, name="last_seen_bucket_allowed"),
        Index(
            "ix_list_targets_list_tg_user",
            "list_id", "tg_user_id",
            unique=True,
        ),
        {"schema": PARSING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    list_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{PARSING_SCHEMA}.lists.id", ondelete="CASCADE"),
        nullable=False,
    )
    tg_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    has_premium: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    last_seen_bucket: Mapped[str] = mapped_column(
        String, nullable=False, default="unknown", server_default="unknown",
    )
