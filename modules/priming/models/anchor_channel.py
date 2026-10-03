"""Канал-переходник, закреплённый в шапке аккаунта (spec §4.6).

Один активный ``PrimingAnchorChannel`` на аккаунт (UNIQUE(account_id)):
второй экземпляр — это уже reset, старая запись помечается ``broken``
или ``reset_required`` и удаляется отдельным шагом (см. промпт 4.3).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import PRIMING_SCHEMA, Base, TimestampMixin
from modules.priming.schemas.enums import AnchorChannelState


class PrimingAnchorChannel(Base, TimestampMixin):
    __tablename__ = "anchor_channels"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            name="uq_anchor_channels_account_id",
        ),
        CheckConstraint(
            "state IN ("
            + ", ".join(f"'{m.value}'" for m in AnchorChannelState)
            + ")",
            name="state_allowed",
        ),
        {"schema": PRIMING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel_tg_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    is_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    pinned_post_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
    pinned_post_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attached_to_profile_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    state: Mapped[str] = mapped_column(
        String, nullable=False,
        default=AnchorChannelState.OK.value,
        server_default=AnchorChannelState.OK.value,
    )
