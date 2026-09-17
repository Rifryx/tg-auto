"""Каноническая ORM-модель кампании модуля commenting (PROJECT-STAGES §1.2).

Живёт в схеме Postgres ``commenting`` (таблицы созданы миграцией 0001).
Регистрируется в общей ``core.models.base.Base`` metadata, поэтому доступна
Alembic и остальному коду; ``core.models.commenting`` только реэкспортирует.
"""

from datetime import time
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Time,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import COMMENTING_SCHEMA, Base, TimestampMixin


class Campaign(Base, TimestampMixin):
    __tablename__ = "campaigns"
    __table_args__ = (
        CheckConstraint(
            "llm_provider IN ('deepseek', 'gemini')",
            name="llm_provider_allowed",
        ),
        CheckConstraint(
            "posting_delay_min_sec >= 0 AND posting_delay_max_sec >= posting_delay_min_sec",
            name="posting_delay_range_valid",
        ),
        {"schema": COMMENTING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Легаси-поле (каналы переехали на аккаунты); допускаем NULL.
    target_channel: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    discussion_group_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    base_system_prompt: Mapped[str] = mapped_column(String, nullable=False)
    # Персона по умолчанию для аккаунтов кампании (у аккаунта своя персона
    # перекрывает). При удалении персоны — SET NULL, кампания продолжает работу.
    persona_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("personas.id", ondelete="SET NULL"), nullable=True
    )
    llm_provider: Mapped[str] = mapped_column(String, nullable=False)
    active_hours_start: Mapped[time] = mapped_column(Time, nullable=False)
    active_hours_end: Mapped[time] = mapped_column(Time, nullable=False)
    active_hours_tz: Mapped[str] = mapped_column(String, nullable=False)
    posting_delay_min_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    posting_delay_max_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
