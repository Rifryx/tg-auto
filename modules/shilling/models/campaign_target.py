"""Целевой канал/чат кампании (куда идёт шиллинг).

Ввод сырой строкой (`@username`, `t.me/xxx`, `t.me/joinchat/…`), затем
воркер её резолвит и заполняет ``resolved_chat_id`` и ``title``.

См. docs/neuroshilling-spec.md § 3.6.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import SHILLING_SCHEMA, Base, CreatedAtMixin


class ShillingTarget(Base, CreatedAtMixin):
    __tablename__ = "campaign_targets"
    __table_args__ = (
        # Одна и та же ссылка не должна дублироваться в рамках одной кампании
        # (raw_input нормализуется в API перед сохранением: strip, lower, без @).
        # post_id в ключе — один канал может быть и на мониторинге (post_id
        # NULL), и добавлен отдельными постами. postgresql_nulls_not_distinct
        # обязателен: иначе Postgres считает NULL'ы различными и дубли обычных
        # целей (post_id IS NULL) перестали бы отсекаться.
        Index(
            "uq_campaign_targets_campaign_raw_post",
            "campaign_id",
            "raw_input",
            "post_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "kind IN ('username', 'invite', 'chat_id')",
            name="ck_campaign_targets_kind_allowed",
        ),
        CheckConstraint(
            "status IN ('pending', 'resolved', 'error')",
            name="ck_campaign_targets_status_allowed",
        ),
        CheckConstraint(
            "mode IN ('link', 'chat', 'channel_post', 'channel_monitor')",
            name="ck_campaign_targets_mode_allowed",
        ),
        {"schema": SHILLING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SHILLING_SCHEMA}.campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    raw_input: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False, default="username")
    # Режим цели — ЧТО именно делаем с этой ссылкой:
    #   link            — авто: канал с обсуждением → комментарии под последним
    #                     постом; чат/группа → пишем прямо в чат (как было).
    #   chat            — всегда пишем прямо в чат/группу, без комментариев.
    #   channel_post    — комментарии под КОНКРЕТНЫМ постом (post_id).
    #   channel_monitor — следим за каналом: на каждый НОВЫЙ пост заходим в
    #                     комментарии (курсор — last_seen_post_id).
    mode: Mapped[str] = mapped_column(
        String, nullable=False, default="link", server_default="link"
    )
    # Конкретный пост для mode='channel_post' (из ссылки t.me/channel/123).
    post_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    # Курсор для mode='channel_monitor': самый свежий пост, который мы уже
    # обработали. Посты старше него не трогаем — иначе при первом включении
    # мониторинга бот бы ломанулся комментировать весь архив канала.
    last_seen_post_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    resolved_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
