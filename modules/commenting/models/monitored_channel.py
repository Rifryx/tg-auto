"""Канал, который мониторит конкретный аккаунт (аккаунт-центрично).

Каждый аккаунт держит СВОЙ список каналов. Аккаунт подписывается на канал в
Telegram и комментирует посты в его discussion-группе. Статус:
* ``pending``  — добавлен, ждёт разрешения ссылки/подписки воркером;
* ``working``  — активно обрабатывается (слушатель поднят, идут комменты);
* ``paused``   — снят с работы (подписка в Telegram может оставаться);
* ``failed``   — не удалось разрешить/подписаться (см. ``error``).
"""

from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import COMMENTING_SCHEMA, Base, TimestampMixin


class MonitoredChannel(Base, TimestampMixin):
    __tablename__ = "monitored_channels"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'working', 'paused', 'failed')",
            name="monitored_channel_status_allowed",
        ),
        # Один и тот же вход (ссылка/юзернейм) не добавляем дважды на аккаунт.
        UniqueConstraint("account_id", "input_ref", name="uq_monitored_account_input"),
        {"schema": COMMENTING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    # Что ввёл пользователь: @username, t.me/xxx или ссылка на папку (addlist).
    input_ref: Mapped[str] = mapped_column(String, nullable=False)
    is_folder: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    # Разрешается воркером через Telethon.
    channel_ref: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    channel_tg_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    discussion_group_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    status: Mapped[str] = mapped_column(String, nullable=False, server_default="pending")
    subscribed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
