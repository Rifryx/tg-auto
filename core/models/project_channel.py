"""Каналы, созданные bulk-action create_channel (этап 8, backlog #3).

Одна строка = один канал, созданный отдельным аккаунтом. Уникальность по
(account_id, channel_tg_id) — исключает дубли при повторном запуске action.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ProjectChannel(Base):
    __tablename__ = "project_channels"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "channel_tg_id", name="uq_project_channels_acc_tg"
        ),
        Index("ix_project_channels_project", "project_id"),
        Index("ix_project_channels_account", "account_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    channel_tg_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_access_hash: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_megagroup: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    pinned_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
