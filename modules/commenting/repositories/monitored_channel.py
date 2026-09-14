from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from core.repositories.base import BaseRepository
from modules.commenting.models import MonitoredChannel


class MonitoredChannelRepository(BaseRepository[MonitoredChannel]):
    """Каналы, которые мониторит аккаунт."""

    model = MonitoredChannel

    def list_by_account(self, account_id: int) -> list[MonitoredChannel]:
        stmt = (
            select(MonitoredChannel)
            .where(MonitoredChannel.account_id == account_id)
            .order_by(MonitoredChannel.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def get_by_account_input(
        self, account_id: int, input_ref: str
    ) -> Optional[MonitoredChannel]:
        stmt = select(MonitoredChannel).where(
            MonitoredChannel.account_id == account_id,
            MonitoredChannel.input_ref == input_ref,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def create(
        self, account_id: int, input_ref: str, is_folder: bool
    ) -> MonitoredChannel:
        ch = MonitoredChannel(
            account_id=account_id,
            input_ref=input_ref,
            is_folder=is_folder,
            status="pending",
        )
        return self._add(ch)

    def list_pending(self) -> list[MonitoredChannel]:
        stmt = select(MonitoredChannel).where(MonitoredChannel.status == "pending")
        return list(self.session.execute(stmt).scalars().all())

    def list_working_by_account(self, account_id: int) -> list[MonitoredChannel]:
        stmt = select(MonitoredChannel).where(
            MonitoredChannel.account_id == account_id,
            MonitoredChannel.status == "working",
        )
        return list(self.session.execute(stmt).scalars().all())

    def list_all_working(self) -> list[MonitoredChannel]:
        """Все каналы в работе (для стартовой загрузки слушателей)."""
        stmt = select(MonitoredChannel).where(MonitoredChannel.status == "working")
        return list(self.session.execute(stmt).scalars().all())

    def list_by_discussion_group(
        self, discussion_group_id: int
    ) -> list[MonitoredChannel]:
        """Working-каналы с данной discussion-группой (у разных аккаунтов)."""
        stmt = select(MonitoredChannel).where(
            MonitoredChannel.discussion_group_id == discussion_group_id,
            MonitoredChannel.status == "working",
        )
        return list(self.session.execute(stmt).scalars().all())

    def mark_working(
        self,
        id_: int,
        *,
        channel_ref: Optional[str],
        channel_tg_id: Optional[int],
        title: Optional[str],
        discussion_group_id: Optional[int],
        subscribed: bool = True,
    ) -> Optional[MonitoredChannel]:
        ch = self.get(id_)
        if ch is None:
            return None
        ch.channel_ref = channel_ref
        ch.channel_tg_id = channel_tg_id
        ch.title = title
        ch.discussion_group_id = discussion_group_id
        ch.subscribed = subscribed
        ch.status = "working"
        ch.error = None
        self.session.flush()
        return ch

    def mark_failed(self, id_: int, error: str) -> Optional[MonitoredChannel]:
        ch = self.get(id_)
        if ch is None:
            return None
        ch.status = "failed"
        ch.error = error[:500]
        self.session.flush()
        return ch

    def delete(self, id_: int) -> bool:
        ch = self.get(id_)
        if ch is None:
            return False
        self.session.delete(ch)
        self.session.flush()
        return True
