"""ORM для parsing.community_items (Discovery сообществ, этап 2).

Одна строка = один канал/чат, обогащённый collector-аккаунтом (участники,
linked-чат, последний пост, флаги). Привязан к ``parsing.lists`` (header).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer,
    String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import PARSING_SCHEMA, Base, CreatedAtMixin


class ParsedCommunityItem(Base, CreatedAtMixin):
    __tablename__ = "community_items"
    __table_args__ = (
        CheckConstraint("kind IN ('channel', 'chat')", name="kind_allowed"),
        Index(
            "ix_community_items_list_ref", "list_id", "input_ref", unique=True,
        ),
        {"schema": PARSING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    list_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{PARSING_SCHEMA}.lists.id", ondelete="CASCADE"),
        nullable=False,
    )
    input_ref: Mapped[str] = mapped_column(String, nullable=False)
    channel_tg_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    access_hash: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    kind: Mapped[str] = mapped_column(String, nullable=False, default="channel")
    participants_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    has_linked_chat: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    linked_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    last_post_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_scam: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_fake: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    slowmode_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    about: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
