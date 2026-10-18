"""Кэш публичного профиля пользователя Mini App (username/имя).

Источник — подписанный initData Telegram. Нужен только для отображения в
админке (по @username вместо числового user_id). Для прав/подписок источник
правды остаётся ``user_id``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class AppUser(Base):
    __tablename__ = "app_users"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
