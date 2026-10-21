"""Задача парсинга с живым прогрессом и управлением (пауза/стоп).

Нужна, чтобы UI после запуска парсинга видел реальный прогресс (лог, счётчики
собранных/отфильтрованных), а не «молча проваливался». Воркер пишет сюда ход
выполнения и периодически читает ``control`` (run/pause/stop), реагируя на
действия пользователя.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import PARSING_SCHEMA, Base, CreatedAtMixin


class ParsingJob(Base, CreatedAtMixin):
    __tablename__ = "jobs"
    __table_args__ = ({"schema": PARSING_SCHEMA},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # pending | running | paused | done | failed | stopped
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    # Команда управления от пользователя: run | pause | stop.
    control: Mapped[str] = mapped_column(
        String, nullable=False, default="run", server_default="run"
    )
    params: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    # Лента лог-строк: [{"ts": iso, "msg": "..."}].
    log: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    raw_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    inserted_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    list_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    meta: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
