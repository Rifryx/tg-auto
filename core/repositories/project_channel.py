"""Репозиторий каналов, созданных bulk-action create_channel (этап 8, backlog #3)."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from core.models.project_channel import ProjectChannel
from core.repositories.base import BaseRepository


class ProjectChannelRepository(BaseRepository[ProjectChannel]):
    model = ProjectChannel

    def create(
        self,
        *,
        account_id: int,
        project_id: Optional[int],
        channel_tg_id: int,
        channel_access_hash: Optional[int],
        title: str,
        username: Optional[str],
        is_megagroup: bool,
        pinned_message_id: Optional[int] = None,
    ) -> ProjectChannel:
        obj = ProjectChannel(
            account_id=account_id,
            project_id=project_id,
            channel_tg_id=channel_tg_id,
            channel_access_hash=channel_access_hash,
            title=title,
            username=username,
            is_megagroup=is_megagroup,
            pinned_message_id=pinned_message_id,
        )
        return self._add(obj)

    def find_by_account_tg(
        self, account_id: int, channel_tg_id: int
    ) -> Optional[ProjectChannel]:
        stmt = select(ProjectChannel).where(
            ProjectChannel.account_id == account_id,
            ProjectChannel.channel_tg_id == channel_tg_id,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_for_project(self, project_id: int) -> list[ProjectChannel]:
        stmt = (
            select(ProjectChannel)
            .where(ProjectChannel.project_id == project_id)
            .order_by(ProjectChannel.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def list_for_account(self, account_id: int) -> list[ProjectChannel]:
        stmt = (
            select(ProjectChannel)
            .where(ProjectChannel.account_id == account_id)
            .order_by(ProjectChannel.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars().all())
