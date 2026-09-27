"""Репозиторий anchor-каналов."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from sqlalchemy import select

from core.repositories.base import BaseRepository
from modules.priming.models import PrimingAnchorChannel


class AnchorChannelRepository(BaseRepository[PrimingAnchorChannel]):
    model = PrimingAnchorChannel

    def get_by_id(self, id_: int) -> Optional[PrimingAnchorChannel]:
        return self.get(id_)

    def get_by_account(self, account_id: int) -> Optional[PrimingAnchorChannel]:
        stmt = select(PrimingAnchorChannel).where(
            PrimingAnchorChannel.account_id == account_id
        )
        return self.session.execute(stmt).scalars().first()

    def list_by_campaign(self, campaign_id: int) -> list[PrimingAnchorChannel]:
        # Anchor-канал живёт на аккаунте, а не на кампании; фильтруем через
        # campaign_accounts.
        from modules.priming.models import PrimingCampaignAccount

        stmt = (
            select(PrimingAnchorChannel)
            .join(
                PrimingCampaignAccount,
                PrimingCampaignAccount.account_id
                == PrimingAnchorChannel.account_id,
            )
            .where(PrimingCampaignAccount.campaign_id == campaign_id)
        )
        return list(self.session.execute(stmt).scalars())

    def create(self, data: Mapping[str, Any]) -> PrimingAnchorChannel:
        obj = PrimingAnchorChannel(**dict(data))
        return self._add(obj)

    def update(
        self, id_: int, data: Mapping[str, Any]
    ) -> Optional[PrimingAnchorChannel]:
        obj = self.get(id_)
        if obj is None:
            return None
        for k, v in data.items():
            setattr(obj, k, v)
        self.session.flush()
        return obj

    def delete_hard(self, id_: int) -> bool:
        obj = self.get(id_)
        if obj is None:
            return False
        self.session.delete(obj)
        self.session.flush()
        return True
