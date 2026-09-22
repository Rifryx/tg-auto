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
from sqlalchemy.dialects.postgresql import ARRAY
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
        CheckConstraint(
            "join_delay_min_sec >= 0 AND join_delay_max_sec >= join_delay_min_sec",
            name="campaign_join_delay_range_valid",
        ),
        CheckConstraint(
            "floodwait_pause_sec >= 0 AND floodwait_quarantine_max >= 1",
            name="campaign_floodwait_valid",
        ),
        CheckConstraint(
            "post_selection_mode IN ('all', 'keywords', 'probability')",
            name="campaign_post_selection_mode_allowed",
        ),
        CheckConstraint(
            "probability_percent BETWEEN 0 AND 100",
            name="campaign_probability_percent_valid",
        ),
        CheckConstraint(
            "work_mode IN ('by_count', 'by_time_window')",
            name="campaign_work_mode_allowed",
        ),
        CheckConstraint(
            "post_scope IN ('new', 'existing', 'mixed')",
            name="campaign_post_scope_allowed",
        ),
        CheckConstraint(
            "min_words >= 0",
            name="campaign_min_words_valid",
        ),
        CheckConstraint(
            "max_comments IS NULL OR max_comments > 0",
            name="campaign_max_comments_valid",
        ),
        CheckConstraint(
            "window_after_post_sec IS NULL OR window_after_post_sec > 0",
            name="campaign_window_after_post_valid",
        ),
        CheckConstraint(
            "pause_between_sec IS NULL OR pause_between_sec >= 0",
            name="campaign_pause_between_valid",
        ),
        CheckConstraint(
            "channel_source_mode IN ('by_account_subscriptions', 'explicit_links')",
            name="campaign_channel_source_mode_allowed",
        ),
        CheckConstraint(
            "on_not_subscribed_action IN ('subscribe_and_notify', 'notify_only')",
            name="campaign_on_not_subscribed_action_allowed",
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
    # Задержки входа в канал и floodwait-политика — применяются пресетами
    # задержек (§ Этап 1). Дефолты соответствуют «Рекомендуемому» пресету.
    join_delay_min_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, default=80, server_default="80"
    )
    join_delay_max_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, default=160, server_default="160"
    )
    floodwait_pause_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, default=120, server_default="120"
    )
    floodwait_quarantine_max: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # ── Режимы отбора постов (§ Этап 2) ────────────────────────────────
    # all: комментируем каждый пост. keywords: только если пост содержит
    # хотя бы одно ключевое слово (case-insensitive substring в
    # message.text). probability: коин-флип по probability_percent.
    post_selection_mode: Mapped[str] = mapped_column(
        String, nullable=False, default="all", server_default="all"
    )
    keywords: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, server_default="{}"
    )
    probability_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )

    # ── Какие посты брать (§ Этап 2) ───────────────────────────────────
    # new: только новые (текущий listener). existing: одноразовый backfill
    # по истории канала (см. DEFERRED-FEATURES). mixed: и то, и другое.
    post_scope: Mapped[str] = mapped_column(
        String, nullable=False, default="new", server_default="new"
    )

    # ── Режим работы + лимиты (§ Этап 2) ──────────────────────────────
    # by_count: жёсткий лимит max_comments (за всю жизнь кампании).
    # by_time_window: комментируем только пока прошло <= window_after_post
    # секунд с публикации поста; pause_between_sec — минимальный интервал
    # между комментариями внутри окна.
    work_mode: Mapped[str] = mapped_column(
        String, nullable=False, default="by_count", server_default="by_count"
    )
    max_comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_words: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    window_after_post_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pause_between_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Целевые каналы (§ Этап 3) ──────────────────────────────────────
    # by_account_subscriptions: источник = MonitoredChannel каждого аккаунта.
    # explicit_links: источник = CampaignChannel этой кампании
    # (usernames / invites / folder-slug'и).
    channel_source_mode: Mapped[str] = mapped_column(
        String, nullable=False, default="explicit_links", server_default="explicit_links"
    )
    # Что делать, если при постинге оказалось, что аккаунт не подписан:
    # subscribe_and_notify — подписаться и залогировать; notify_only —
    # только уведомить и пропустить пост.
    on_not_subscribed_action: Mapped[str] = mapped_column(
        String, nullable=False, default="notify_only", server_default="notify_only"
    )
