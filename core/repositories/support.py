"""Репозиторий поддержки (тред сообщений + релеи ответов менеджера)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from core.models.support import SupportMessage, SupportRelay


class SupportRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ── тред сообщений ──────────────────────────────────────────────────────
    def add_message(
        self,
        *,
        user_id: str,
        direction: str,
        text: str,
        username: Optional[str] = None,
    ) -> SupportMessage:
        msg = SupportMessage(
            user_id=user_id, direction=direction, text=text, username=username
        )
        self.session.add(msg)
        self.session.flush()
        return msg

    def thread(self, user_id: str, limit: int = 200) -> list[SupportMessage]:
        stmt = (
            select(SupportMessage)
            .where(SupportMessage.user_id == user_id)
            .order_by(SupportMessage.created_at.asc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars().all())

    def purge_older_than(self, days: int) -> int:
        """Удалить сообщения старше N дней (история хранится ограниченное время)."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = self.session.execute(
            delete(SupportMessage).where(SupportMessage.created_at < cutoff)
        )
        return int(result.rowcount or 0)

    # ── релеи (chat_id, message_id) → user_id ───────────────────────────────
    def add_relay(self, *, chat_id: str, message_id: int, user_id: str) -> None:
        self.session.add(
            SupportRelay(chat_id=chat_id, message_id=message_id, user_id=user_id)
        )
        self.session.flush()

    def user_for_relay(self, *, chat_id: str, message_id: int) -> Optional[str]:
        stmt = select(SupportRelay.user_id).where(
            SupportRelay.chat_id == chat_id,
            SupportRelay.message_id == message_id,
        )
        return self.session.execute(stmt).scalar_one_or_none()
