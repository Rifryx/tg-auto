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

    def delete(self, id_: int) -> bool:
        ch = self.get(id_)
        if ch is None:
            return False
        self.session.delete(ch)
        self.session.flush()
        return True
