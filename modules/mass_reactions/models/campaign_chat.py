"""Чат кампании масс-реакций + жёсткое закрепление за аккаунтом.

Один чат закреплён за одним аккаунтом (``account_id``), чтобы при замене база
не перемешивалась (как ``monitored_channels.account_id`` в нейрокомментинге).
Счётчик ``reaction_counter`` ведёт «каждое N-е сообщение» на уровне чата.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import MASS_REACTIONS_SCHEMA, Base, CreatedAtMixin
from modules.mass_reactions.schemas.enums import ChatNotifyMode, ChatState


class MassReactionCampaignChat(Base, CreatedAtMixin):
    __tablename__ = "campaign_chats"
    __table_args__ = (
        # Один и тот же чат в кампании не дублируем (по введённой ссылке).
        UniqueConstraint(
            "campaign_id", "chat_ref",
            name="uq_campaign_chats_campaign_id_chat_ref",
        ),
        CheckConstraint(
            "state IN ("
            + ", ".join(f"'{m.value}'" for m in ChatState)
            + ")",
            name="state_allowed",
        ),
        CheckConstraint(
            "notify_mode IN ("
            + ", ".join(f"'{m.value}'" for m in ChatNotifyMode)
            + ")",
            name="notify_mode_allowed",
        ),
        CheckConstraint(
            "reaction_counter >= 0 AND reactions_total >= 0",
            name="chat_counters_nonneg",
        ),
        {"schema": MASS_REACTIONS_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{MASS_REACTIONS_SCHEMA}.campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Закреплённый аккаунт. NULL — ещё не назначен (tick подберёт из пула).
    account_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Как пользователь ввёл чат (@username / t.me/... / id). Стабильный ключ.
    chat_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    # Резолв в Telegram id (entity.id, положительный). NULL — ещё не зарезолвлен.
    chat_tg_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    state: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=ChatState.PENDING.value,
        server_default=ChatState.PENDING.value,
    )
    # Что делать, если чата нет в подписках закреплённого аккаунта.
    notify_mode: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=ChatNotifyMode.NOTIFY_ONLY.value,
        server_default=ChatNotifyMode.NOTIFY_ONLY.value,
    )

    # Счётчик входящих сообщений для «каждое N-е» (на уровне чата).
    reaction_counter: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    reactions_total: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_reacted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
