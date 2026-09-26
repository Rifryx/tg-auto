"""Репозиторий кампаний модуля НейроШиллинг."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sqlalchemy import select

from core.repositories.base import BaseRepository
from modules.shilling.models import ShillingCampaign

if TYPE_CHECKING:  # pragma: no cover — типы Pydantic-схем появятся в промпте 1.5
    from modules.shilling.schemas.campaign import CampaignCreate, CampaignUpdate


class CampaignRepository(BaseRepository[ShillingCampaign]):
    model = ShillingCampaign

    def list_all(self) -> list[ShillingCampaign]:  # override для порядка
        stmt = select(ShillingCampaign).order_by(ShillingCampaign.created_at.desc())
        return list(self.session.execute(stmt).scalars())

    def list_by_status(self, status: str) -> list[ShillingCampaign]:
        stmt = (
            select(ShillingCampaign)
            .where(ShillingCampaign.status == status)
            .order_by(ShillingCampaign.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars())

    def list_active(self) -> list[ShillingCampaign]:
        """Все включённые кампании со статусом running (для планировщика)."""
        stmt = select(ShillingCampaign).where(
            ShillingCampaign.enabled.is_(True),
            ShillingCampaign.status == "running",
        )
        return list(self.session.execute(stmt).scalars())

    def create(self, data: "CampaignCreate") -> ShillingCampaign:
        campaign = ShillingCampaign(**data.model_dump(exclude_unset=True))
        return self._add(campaign)

    def update(self, id_: int, data: "CampaignUpdate") -> Optional[ShillingCampaign]:
        campaign = self.get(id_)
        if campaign is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(campaign, field, value)
        self.session.flush()
        return campaign

    def set_status(self, id_: int, status: str) -> Optional[ShillingCampaign]:
        """Обновляет только status. Валидация значения — на уровне сервиса."""
        campaign = self.get(id_)
        if campaign is None:
            return None
        campaign.status = status
        self.session.flush()
        return campaign

    def delete(self, id_: int) -> bool:
        campaign = self.get(id_)
        if campaign is None:
            return False
        self.session.delete(campaign)
        self.session.flush()
        return True
