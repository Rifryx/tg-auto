"""ORM-модель кампании масс-реакций.

Живёт в схеме Postgres ``mass_reactions``. Конфигурация кампании и runtime-статус;
аккаунты и чаты — в отдельных таблицах (``campaign_accounts`` / ``campaign_chats``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import MASS_REACTIONS_SCHEMA, Base, TimestampMixin
from modules.mass_reactions.schemas.enums import (
    ChatSourceMode,
    HumanizerMode,
    MassReactionCampaignStatus,
    ReactionStrategy,
    WarmupProfile,
)


def _in_clause(enum_cls) -> str:
    return ", ".join(f"'{m.value}'" for m in enum_cls)


class MassReactionCampaign(Base, TimestampMixin):
    """Одна кампания масс-реакций."""

    __tablename__ = "campaigns"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_in_clause(MassReactionCampaignStatus)})",
            name="status_allowed",
        ),
        CheckConstraint(
            f"chat_source_mode IN ({_in_clause(ChatSourceMode)})",
            name="chat_source_mode_allowed",
        ),
        CheckConstraint(
            f"reaction_strategy IN ({_in_clause(ReactionStrategy)})",
            name="reaction_strategy_allowed",
        ),
        CheckConstraint(
            f"warmup_profile IN ({_in_clause(WarmupProfile)})",
            name="warmup_profile_allowed",
        ),
        CheckConstraint(
            f"humanizer_mode IN ({_in_clause(HumanizerMode)})",
            name="humanizer_mode_allowed",
        ),
        CheckConstraint(
            "jsonb_array_length(reaction_emojis) >= 1",
            name="reaction_emojis_nonempty",
        ),
        CheckConstraint(
            "every_n_message >= 1 AND every_n_message <= 50",
            name="every_n_message_valid",
        ),
        CheckConstraint(
            "probability_percent >= 1 AND probability_percent <= 100",
            name="probability_percent_valid",
        ),
        CheckConstraint(
            "first_n_in_burst >= 1 AND first_n_in_burst <= 10",
            name="first_n_in_burst_valid",
        ),
        CheckConstraint(
            "duration_hours >= 1 AND duration_hours <= 72",
            name="duration_hours_valid",
        ),
        CheckConstraint(
            "skip_messages_older_than_days >= 0 "
            "AND skip_messages_older_than_days <= 30",
            name="skip_older_days_valid",
        ),
        CheckConstraint(
            "delay_between_reactions_sec_min >= 0 "
            "AND delay_between_reactions_sec_max >= delay_between_reactions_sec_min",
            name="delay_range_valid",
        ),
        CheckConstraint(
            "join_pause_sec >= 0",
            name="join_pause_sec_valid",
        ),
        CheckConstraint(
            "daily_limit_per_account >= 1 AND daily_limit_per_account <= 500",
            name="daily_limit_valid",
        ),
        CheckConstraint(
            "max_chats_per_account >= 1 AND max_chats_per_account <= 20",
            name="max_chats_per_account_valid",
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
            "quiet_hours_start >= 0 AND quiet_hours_start < 24 "
            "AND quiet_hours_end > quiet_hours_start "
            "AND quiet_hours_end <= 24",
            name="quiet_hours_window_valid",
        ),
        {"schema": MASS_REACTIONS_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=MassReactionCampaignStatus.DRAFT.value,
        server_default=MassReactionCampaignStatus.DRAFT.value,
    )

    # ── Источник чатов ────────────────────────────────────────────────
    chat_source_mode: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=ChatSourceMode.BY_SUBSCRIPTIONS.value,
        server_default=ChatSourceMode.BY_SUBSCRIPTIONS.value,
    )

    # ── Параметры реакций ─────────────────────────────────────────────
    # Белый список выбранных эмодзи (strings). Пустой запрещён (CheckConstraint).
    reaction_emojis: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default="'[]'::jsonb"
    )
    reaction_strategy: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=ReactionStrategy.RANDOM.value,
        server_default=ReactionStrategy.RANDOM.value,
    )
    # «Реагировать на каждое N-е сообщение» — счётчик на уровне чата + вероятность.
    every_n_message: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    probability_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )
    # Только первые N сообщений в «пачке» (экономия лимитов).
    first_n_in_burst: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )

    # ── Окно работы ───────────────────────────────────────────────────
    duration_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, default=24, server_default="24"
    )
    skip_messages_older_than_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    # ── Задержки (в секундах; UI показывает минуты) ───────────────────
    delay_between_reactions_sec_min: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60, server_default="60"
    )
    delay_between_reactions_sec_max: Mapped[int] = mapped_column(
        Integer, nullable=False, default=300, server_default="300"
    )
    join_pause_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, default=120, server_default="120"
    )

    # ── Аккаунты и лимиты ─────────────────────────────────────────────
    warmup_profile: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=WarmupProfile.WARM.value,
        server_default=WarmupProfile.WARM.value,
    )
    humanizer_mode: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=HumanizerMode.BALANCED.value,
        server_default=HumanizerMode.BALANCED.value,
    )
    daily_limit_per_account: Mapped[int] = mapped_column(
        Integer, nullable=False, default=200, server_default="200"
    )
    max_chats_per_account: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default="5"
    )

    # ── Ошибки / безопасность ─────────────────────────────────────────
    flood_wait_pause_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3600, server_default="3600"
    )
    max_flood_waits_per_account: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    quiet_hours_start: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    quiet_hours_end: Mapped[int] = mapped_column(
        Integer, nullable=False, default=24, server_default="24"
    )

    # ── Runtime ───────────────────────────────────────────────────────
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Автозавершение кампании: started_at + duration_hours. Проставляется при запуске.
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Свободные метаданные под будущие поля без миграции (напр. веса эмодзи).
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="'{}'::jsonb"
    )
