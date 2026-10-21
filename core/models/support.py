"""Поддержка: чат пользователя с менеджером внутри приложения.

* ``SupportMessage`` — одно сообщение треда. ``direction``: ``user`` (от
  пользователя) или ``manager`` (ответ менеджера). Тред пользователя — все его
  сообщения по ``user_id`` в порядке времени.
* ``SupportRelay`` — связка «сообщение бота в чате менеджера → user_id». Когда
  менеджер отвечает реплаем на это сообщение, бот по (chat_id, message_id)
  понимает, какому пользователю адресован ответ (менеджер не теряется в тредах).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class SupportMessage(Base):
    __tablename__ = "support_messages"
    __table_args__ = (
        Index("ix_support_messages_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    username: Mapped[str | None] = mapped_column(String, nullable=True)
    # user | manager
    direction: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SupportRelay(Base):
    __tablename__ = "support_relays"
    __table_args__ = (
        Index("ix_support_relays_chat_msg", "chat_id", "message_id", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chat_id: Mapped[str] = mapped_column(String, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
