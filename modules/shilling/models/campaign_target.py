"""Целевой канал/чат кампании (куда идёт шиллинг).

Ввод сырой строкой (`@username`, `t.me/xxx`, `t.me/joinchat/…`), затем
воркер её резолвит и заполняет ``resolved_chat_id`` и ``title``.

См. docs/neuroshilling-spec.md § 3.6.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import SHILLING_SCHEMA, Base, CreatedAtMixin


class ShillingTarget(Base, CreatedAtMixin):
    __tablename__ = "campaign_targets"
    __table_args__ = (
        # Одна и та же ссылка не должна дублироваться в рамках одной кампании
        # (raw_input нормализуется в API перед сохранением: strip, lower, без @).
        UniqueConstraint(
            "campaign_id",
            "raw_input",
            name="uq_campaign_targets_campaign_id_raw_input",
        ),
        CheckConstraint(
            "kind IN ('username', 'invite', 'chat_id')",
            name="ck_campaign_targets_kind_allowed",
        ),
        CheckConstraint(
            "status IN ('pending', 'resolved', 'error')",
            name="ck_campaign_targets_status_allowed",
        ),
        {"schema": SHILLING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SHILLING_SCHEMA}.campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    raw_input: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False, default="username")
    resolved_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
