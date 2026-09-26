"""Целевые каналы кампании и черный список (§ Этап 3).

* :class:`CampaignChannel` — «на что подписываться и где комментировать»,
  задаётся на уровне кампании. Используется только при
  ``campaigns.channel_source_mode='explicit_links'``. Для
  ``by_account_subscriptions`` источник — существующие
  :class:`MonitoredChannel` каждого аккаунта.
* :class:`ChannelBlacklist` — черный список каналов на кампанию. Может
  пополняться вручную и автоматически воркером (при access-ошибках).

Резолвер (ссылка → chat_id, подписка при необходимости) живёт в воркере
и на текущий момент отложен (см. DEFERRED-FEATURES [E3.2]). Здесь —
только модели, чтобы UI и CRUD работали.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import COMMENTING_SCHEMA, Base, TimestampMixin


class CampaignChannel(Base, TimestampMixin):
    """Целевой канал/чат/папка, привязанный к кампании."""

    __tablename__ = "campaign_channels"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('username', 'invite', 'folder')",
            name="campaign_channel_kind_allowed",
        ),
        # Дедуп: одна и та же строка не добавляется дважды в одну кампанию.
        UniqueConstraint(
            "campaign_id", "raw_input", name="uq_campaign_channels_raw"
        ),
        {"schema": COMMENTING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{COMMENTING_SCHEMA}.campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Что ввёл пользователь: @username, t.me/xxx, t.me/joinchat/..., t.me/addlist/...
    raw_input: Mapped[str] = mapped_column(String, nullable=False)
    # Классификация ввода на клиенте (проверяется на сервере).
    kind: Mapped[str] = mapped_column(String, nullable=False)
    # Разрешается воркером; NULL до первой резолюции.
    resolved_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Ошибка последней попытки резолюции/подписки — для UI-статуса.
    last_error: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class ChannelBlacklist(Base, TimestampMixin):
    """Черный список каналов для кампании (ручной + авто)."""

    __tablename__ = "channel_blacklist"
    __table_args__ = (
        # Один из идентификаторов должен присутствовать.
        CheckConstraint(
            "chat_id IS NOT NULL OR username IS NOT NULL",
            name="channel_blacklist_identifier_present",
        ),
        # Простой UNIQUE-дедуп по обоим ключам одновременно. Частичные
        # partial-UNIQUE (по chat_id и по username раздельно) заведены в
        # миграции — на уровне модели их не декларируем.
        UniqueConstraint(
            "campaign_id",
            "chat_id",
            "username",
            name="uq_channel_blacklist_all",
        ),
        {"schema": COMMENTING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{COMMENTING_SCHEMA}.campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # True = добавлен автоматически воркером; False = пользователем вручную.
    auto: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


ALERT_KINDS = ("not_subscribed", "auto_subscribed", "access_lost", "blacklisted")


class ChannelAlert(Base):
    """Событие по каналу для уведомлений (E3.2): дашборд, бот, детали кампании.

    Отдельно от health_events: те кормят предиктор риска бана, а «аккаунт не
    подписан на канал» — не сигнал бана.
    """

    __tablename__ = "channel_alerts"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('not_subscribed', 'auto_subscribed', 'access_lost', 'blacklisted')",
            name="channel_alert_kind_allowed",
        ),
        {"schema": COMMENTING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    campaign_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey(f"{COMMENTING_SCHEMA}.campaigns.id", ondelete="CASCADE"),
        nullable=True,
    )
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    channel_ref: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    resolved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
