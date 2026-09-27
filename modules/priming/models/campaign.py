"""ORM-модель кампании модуля Telegram-Прайминг.

Живёт в схеме Postgres ``priming`` (создана миграцией 0039_priming_schema).
См. docs/priming-spec.md §4.1.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import PRIMING_SCHEMA, Base, TimestampMixin
from modules.priming.schemas.enums import (
    HumanizerMode,
    PrimingCampaignStatus,
    PrimingMode,
    TriggerAction,
    WarmupProfile,
)


def _in_clause(enum_cls) -> str:
    values = ", ".join(f"'{m.value}'" for m in enum_cls)
    return values


class PrimingCampaign(Base, TimestampMixin):
    """Одна кампания прайминга.

    Аккаунты и цели живут в отдельных таблицах (``campaign_accounts`` /
    ``campaign_targets``). Тут — только конфигурация кампании и runtime-статус.
    """

    __tablename__ = "campaigns"
    # NAMING_CONVENTION (core.models.base) сам префиксует имена
    # CheckConstraint'ов как ``ck_<tablename>_<name>``.
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_in_clause(PrimingCampaignStatus)})",
            name="status_allowed",
        ),
        CheckConstraint(
            f"mode IN ({_in_clause(PrimingMode)})",
            name="mode_allowed",
        ),
        CheckConstraint(
            f"trigger_action IN ({_in_clause(TriggerAction)})",
            name="trigger_action_allowed",
        ),
        CheckConstraint(
            f"humanizer_mode IN ({_in_clause(HumanizerMode)})",
            name="humanizer_mode_allowed",
        ),
        CheckConstraint(
            f"warmup_profile IN ({_in_clause(WarmupProfile)})",
            name="warmup_profile_allowed",
        ),
        CheckConstraint(
            "delay_between_targets_sec_min >= 0 "
            "AND delay_between_targets_sec_max >= delay_between_targets_sec_min",
            name="delay_range_valid",
        ),
        CheckConstraint(
            "flood_wait_pause_sec > 0",
            name="flood_wait_pause_valid",
        ),
        CheckConstraint(
            "max_flood_waits_per_account > 0",
            name="max_flood_waits_valid",
        ),
        CheckConstraint(
            "daily_limit_per_account >= 1 AND daily_limit_per_account <= 500",
            name="daily_limit_valid",
        ),
        CheckConstraint(
            "stop_on_privacy_rate >= 0 AND stop_on_privacy_rate <= 1",
            name="stop_on_privacy_rate_valid",
        ),
        {"schema": PRIMING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    # ── Режим и триггер ────────────────────────────────────────────────
    mode: Mapped[str] = mapped_column(
        String, nullable=False, default=PrimingMode.PRIMING.value,
        server_default=PrimingMode.PRIMING.value,
    )
    trigger_action: Mapped[str] = mapped_column(String, nullable=False)
    humanizer_mode: Mapped[str] = mapped_column(
        String, nullable=False, default=HumanizerMode.BALANCED.value,
        server_default=HumanizerMode.BALANCED.value,
    )

    # ── Темп и лимиты ──────────────────────────────────────────────────
    delay_between_targets_sec_min: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60, server_default="60"
    )
    delay_between_targets_sec_max: Mapped[int] = mapped_column(
        Integer, nullable=False, default=180, server_default="180"
    )
    flood_wait_pause_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, default=500, server_default="500"
    )
    max_flood_waits_per_account: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    daily_limit_per_account: Mapped[int] = mapped_column(
        Integer, nullable=False, default=35, server_default="35"
    )
    warmup_profile: Mapped[str] = mapped_column(
        String, nullable=False, default=WarmupProfile.WARM.value,
        server_default=WarmupProfile.WARM.value,
    )

    # ── Фильтры аудитории ──────────────────────────────────────────────
    require_username: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    premium_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    exclude_bots: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    exclude_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    exclude_admins: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # ── Автостоп ───────────────────────────────────────────────────────
    stop_on_privacy_rate: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.3, server_default="0.3"
    )

    # ── Runtime ────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String, nullable=False, default=PrimingCampaignStatus.DRAFT.value,
        server_default=PrimingCampaignStatus.DRAFT.value,
    )
    # dry_run — «безопасный прогон» без Telethon-вызовов; результаты
    # симулируются из распределения по docs/priming-triggers.md
    # (см. modules/priming/worker/trigger.py). Флаг живёт на кампании
    # и берётся executor'ом в момент запуска.
    dry_run: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Владелец ───────────────────────────────────────────────────────
    # На созданной FK на users сейчас нет (в проекте пока нет отдельной
    # таблицы users; user_id хранится как BIGINT в других модулях так же).
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
