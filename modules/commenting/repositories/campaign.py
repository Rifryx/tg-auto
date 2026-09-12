from __future__ import annotations

from typing import Optional

from core.repositories.base import BaseRepository
from modules.commenting.models import Campaign
from modules.commenting.schemas import CampaignCreate, CampaignUpdate


class CampaignRepository(BaseRepository[Campaign]):
    model = Campaign

    def create(self, data: CampaignCreate) -> Campaign:
        campaign = Campaign(**data.model_dump())
        return self._add(campaign)

    def update(self, id_: int, data: CampaignUpdate) -> Optional[Campaign]:
        campaign = self.get(id_)
        if campaign is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(campaign, field, value)
        self.session.flush()
        return campaign

    def delete(self, id_: int) -> bool:
        campaign = self.get(id_)
        if campaign is None:
            return False
        self.session.delete(campaign)
        self.session.flush()
        return True
