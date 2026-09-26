"""Чёрный список каналов кампании (не постим сюда).

Пополняется вручную оператором ИЛИ автоматически воркером при получении
``UserBannedInChannel`` / ``ChatWriteForbidden`` (флаг ``auto=True``).

Уникальность по (campaign_id, chat_id) и (campaign_id, username): один и
тот же канал не попадёт в ЧС дважды.

См. docs/neuroshilling-spec.md § 3.8.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import SHILLING_SCHEMA, Base, TimestampMixin


class ShillingBlacklist(Base, TimestampMixin):
    __tablename__ = "blacklist"
    __table_args__ = (
        # Хотя бы один из идентификаторов должен быть задан.
        CheckConstraint(
            "chat_id IS NOT NULL OR username IS NOT NULL",
            name="ck_blacklist_identifier_present",
        ),
        # Частичные уникальные индексы (partial unique) — один и тот же
        # chat_id/username не дублируется в рамках одной кампании; NULL
        # исключены, чтобы записи с только username не конфликтовали с
        # записями только с chat_id.
        Index(
            "uq_blacklist_campaign_id_chat_id",
            "campaign_id",
            "chat_id",
            unique=True,
            postgresql_where=text("chat_id IS NOT NULL"),
        ),
        Index(
            "uq_blacklist_campaign_id_username",
            "campaign_id",
            "username",
            unique=True,
            postgresql_where=text("username IS NOT NULL"),
        ),
        {"schema": SHILLING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SHILLING_SCHEMA}.campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    auto: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
