"""Репозитории целевых каналов и черного списка (§ Этап 3)."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import and_, or_, select

from core.repositories.base import BaseRepository
from modules.commenting.models.channel_source import (
    CampaignChannel,
    ChannelBlacklist,
)
from modules.commenting.schemas.channel_source import (
    CampaignChannelCreate,
    ChannelBlacklistCreate,
)


class CampaignChannelRepository(BaseRepository[CampaignChannel]):
    model = CampaignChannel

    def list_by_campaign(self, campaign_id: int) -> list[CampaignChannel]:
        stmt = (
            select(CampaignChannel)
            .where(CampaignChannel.campaign_id == campaign_id)
            .order_by(CampaignChannel.created_at.asc())
        )
        return list(self.session.execute(stmt).scalars())

    def create(
        self, campaign_id: int, data: CampaignChannelCreate
    ) -> CampaignChannel:
        channel = CampaignChannel(
            campaign_id=campaign_id,
            raw_input=data.raw_input.strip(),
            kind=data.kind or "username",
        )
        return self._add(channel)

    def delete(self, campaign_id: int, channel_id: int) -> bool:
        obj = self.session.get(CampaignChannel, channel_id)
        if obj is None or obj.campaign_id != campaign_id:
            return False
        self.session.delete(obj)
        self.session.flush()
        return True


class ChannelBlacklistRepository(BaseRepository[ChannelBlacklist]):
    model = ChannelBlacklist

    def list_by_campaign(self, campaign_id: int) -> list[ChannelBlacklist]:
        stmt = (
            select(ChannelBlacklist)
            .where(ChannelBlacklist.campaign_id == campaign_id)
            .order_by(ChannelBlacklist.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars())

    def create(
        self,
        campaign_id: int,
        data: ChannelBlacklistCreate,
        *,
        auto: bool = False,
    ) -> ChannelBlacklist:
        entry = ChannelBlacklist(
            campaign_id=campaign_id,
            chat_id=data.chat_id,
            username=(data.username or None),
            reason=data.reason,
            auto=auto,
        )
        return self._add(entry)

    def delete(self, campaign_id: int, entry_id: int) -> bool:
        obj = self.session.get(ChannelBlacklist, entry_id)
        if obj is None or obj.campaign_id != campaign_id:
            return False
        self.session.delete(obj)
        self.session.flush()
        return True

    def find(
        self,
        campaign_id: int,
        *,
        chat_id: Optional[int] = None,
        username: Optional[str] = None,
    ) -> Optional[ChannelBlacklist]:
        """Возвращает запись, если канал уже в ЧС кампании — воркеру для чека."""
        if chat_id is None and not username:
            return None
        stmt = select(ChannelBlacklist).where(
            ChannelBlacklist.campaign_id == campaign_id
        )
        clauses = []
        if chat_id is not None:
            clauses.append(ChannelBlacklist.chat_id == chat_id)
        if username:
            clauses.append(ChannelBlacklist.username == username)
        stmt = stmt.where(or_(*clauses)) if len(clauses) > 1 else stmt.where(and_(*clauses))
        return self.session.execute(stmt).scalars().first()
