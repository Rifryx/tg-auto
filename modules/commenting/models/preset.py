"""Пресеты для нейрокомментинга (§ Этап 1).

Два типа пресетов:

* :class:`AccountPreset` — «рабочий набор аккаунтов». Пользовательский,
  переиспользуется при создании новой кампании: выбрал пресет —
  подтянулись все привязанные account_id, не нужно тыкать по одному.
* :class:`DelayPreset` — набор задержек комментирования (Мин / Рекоменд /
  Макс — три системных пресета сидятся миграцией, плюс пользовательские).
  Значения применяются к :class:`Campaign` (posting_delay_*, join_delay_*,
  floodwait_*), поля добавлены в той же миграции.

Оба пресета скоупятся по ``owner_user_id`` (Telegram user id, строка):
- ``AccountPreset``: всегда user-owned.
- ``DelayPreset``: ``is_system=True → owner_user_id=NULL``; иначе owned.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import COMMENTING_SCHEMA, Base, TimestampMixin


class AccountPreset(Base, TimestampMixin):
    __tablename__ = "account_presets"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id", "name", name="uq_account_presets_owner_name"
        ),
        {"schema": COMMENTING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # ARRAY[BigInteger] — id аккаунтов; FK на accounts.id не ставим намеренно:
    # удаление аккаунта не должно ломать пресет (чистим лениво при применении).
    account_ids: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger), nullable=False, server_default="{}"
    )


class DelayPreset(Base, TimestampMixin):
    __tablename__ = "delay_presets"
    __table_args__ = (
        CheckConstraint(
            "posting_delay_min_sec >= 0 AND "
            "posting_delay_max_sec >= posting_delay_min_sec",
            name="delay_preset_posting_range_valid",
        ),
        CheckConstraint(
            "join_delay_min_sec >= 0 AND join_delay_max_sec >= join_delay_min_sec",
            name="delay_preset_join_range_valid",
        ),
        CheckConstraint(
            "floodwait_pause_sec >= 0 AND floodwait_quarantine_max >= 1",
            name="delay_preset_floodwait_valid",
        ),
        # Системные пресеты — уникальны по имени (owner = NULL); user-пресеты
        # уникальны в рамках владельца.
        UniqueConstraint(
            "owner_user_id", "name", name="uq_delay_presets_owner_name"
        ),
        {"schema": COMMENTING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # NULL → системный пресет (Мин / Рекоменд / Макс); иначе пользовательский.
    owner_user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    posting_delay_min_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    posting_delay_max_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    join_delay_min_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    join_delay_max_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    floodwait_pause_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    floodwait_quarantine_max: Mapped[int] = mapped_column(Integer, nullable=False)
