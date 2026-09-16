from datetime import time
from typing import Any, Optional

from sqlalchemy import BigInteger, String, Time
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, CreatedAtMixin


class Persona(Base, CreatedAtMixin):
    __tablename__ = "personas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    avatar_template_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    bio_template: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    personality_tags: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # ── Warmup Engine (этап 10 УТП) ──────────────────────────────────────────
    # Список публичных Telegram username'ов, соответствующих интересам персоны.
    # Warmup action'ы берут отсюда каналы для subscribe/read_history вместо
    # общей константы. Пустой список = fallback на глобальные DISCOVERY_*.
    interests: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    # tz имени (IANA) — определяет ЛОКАЛЬНОЕ окно активности этой персоны.
    # NULL = использовать глобальный default из core.config.
    timezone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Локальное окно активности. Оба поля NULL = использовать глобальные
    # default_active_hours_start/end. Обе колонки задаются вместе или пусты.
    active_hours_start: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
    active_hours_end: Mapped[Optional[time]] = mapped_column(Time, nullable=True)
