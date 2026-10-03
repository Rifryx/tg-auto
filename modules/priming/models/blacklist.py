"""Blacklist целей прайминга (spec §4.9).

- Владелец: ``owner_user_id`` или NULL (глобальный на всех кампаний
  сервиса).
- Ключи идентификации: tg_user_id, username, phone — любой из них.
- Причина: типовые случаи из :class:`BlacklistReason`.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Index,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import PRIMING_SCHEMA, Base, CreatedAtMixin
from modules.priming.schemas.enums import BlacklistReason


class PrimingBlacklist(Base, CreatedAtMixin):
    __tablename__ = "blacklist"
    __table_args__ = (
        CheckConstraint(
            "reason IN ("
            + ", ".join(f"'{m.value}'" for m in BlacklistReason)
            + ")",
            name="reason_allowed",
        ),
        CheckConstraint(
            "tg_user_id IS NOT NULL OR username IS NOT NULL OR phone IS NOT NULL",
            name="identity_present",
        ),
        # Быстрый lookup (owner, key) — используем в match().
        Index("ix_blacklist_owner_tg_user_id", "owner_user_id", "tg_user_id"),
        Index("ix_blacklist_owner_username", "owner_user_id", "username"),
        Index("ix_blacklist_owner_phone", "owner_user_id", "phone"),
        {"schema": PRIMING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # NULL — глобальный blacklist (действует у всех пользователей сервиса).
    owner_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    tg_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    reason: Mapped[str] = mapped_column(String, nullable=False)
