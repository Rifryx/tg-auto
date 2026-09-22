from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from core.repositories.base import BaseRepository
from modules.commenting.models import CampaignAccount
from modules.commenting.schemas import CampaignAccountCreate
from modules.commenting.schemas.campaign_account import CampaignAccountUpdate


class CampaignAccountRepository(BaseRepository[CampaignAccount]):
    """Привязки аккаунтов к кампаниям. account_id эксклюзивен (UNIQUE)."""

    model = CampaignAccount

    def create(self, data: CampaignAccountCreate) -> CampaignAccount:
        link = CampaignAccount(**data.model_dump())
        return self._add(link)

    def get(self, campaign_id: int, account_id: int) -> Optional[CampaignAccount]:
        # Композитный PK (campaign_id, account_id).
        return self.session.get(CampaignAccount, (campaign_id, account_id))

    def get_by_account(self, account_id: int) -> Optional[CampaignAccount]:
        stmt = select(CampaignAccount).where(CampaignAccount.account_id == account_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def list_by_campaign(self, campaign_id: int) -> list[CampaignAccount]:
        stmt = (
            select(CampaignAccount)
            .where(CampaignAccount.campaign_id == campaign_id)
            .order_by(CampaignAccount.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def update(
        self, campaign_id: int, account_id: int, data: CampaignAccountUpdate
    ) -> Optional[CampaignAccount]:
        link = self.get(campaign_id, account_id)
        if link is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(link, field, value)
        self.session.flush()
        return link

    def delete(self, campaign_id: int, account_id: int) -> bool:
        link = self.get(campaign_id, account_id)
        if link is None:
            return False
        self.session.delete(link)
        self.session.flush()
        return True
