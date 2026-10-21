"""Простое key-value хранилище настроек приложения (редактируемых из админки).

Используется для контента, который раньше был «зашит» в код и не менялся без
деплоя: блок «О приложении», конфиг поддержки (контакт менеджера) и т.п.
Значение хранится как JSONB — одна строка на логический раздел (key).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
