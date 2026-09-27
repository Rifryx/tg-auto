"""ORM для parsing.lists (spec §8, промпт 3.2b)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import PARSING_SCHEMA, Base, CreatedAtMixin


_SOURCE_KINDS_SQL = "source_kind IN ('chat_messages', 'chat_members', 'manual_list', 'upload_csv')"


class ParsedList(Base, CreatedAtMixin):
    __tablename__ = "lists"
    __table_args__ = (
        CheckConstraint(_SOURCE_KINDS_SQL, name="source_kind_allowed"),
        CheckConstraint(
            "raw_count >= 0 AND after_filters_count >= 0 "
            "AND after_filters_count <= raw_count",
            name="counts_valid",
        ),
        Index("ix_lists_owner_created", "owner_user_id", "created_at"),
        {"schema": PARSING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_kind: Mapped[str] = mapped_column(String, nullable=False)
    chat_ref: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    days_window: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    min_messages: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    raw_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    after_filters_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    filters_breakdown: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    parsed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
