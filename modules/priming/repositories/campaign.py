"""Репозиторий кампаний прайминга (промпт 1.5)."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from sqlalchemy import select

from core.repositories.base import BaseRepository
from modules.priming.models import PrimingCampaign


class CampaignRepository(BaseRepository[PrimingCampaign]):
    model = PrimingCampaign

    # get(id_) наследуется от BaseRepository.
    def get_by_id(self, id_: int) -> Optional[PrimingCampaign]:
        return self.get(id_)

    def list_all(self) -> list[PrimingCampaign]:  # override — сортировка
        stmt = select(PrimingCampaign).order_by(PrimingCampaign.created_at.desc())
        return list(self.session.execute(stmt).scalars())

    def list_by_status(self, status: str) -> list[PrimingCampaign]:
        stmt = (
            select(PrimingCampaign)
            .where(PrimingCampaign.status == status)
            .order_by(PrimingCampaign.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars())

    def create(self, data: Mapping[str, Any]) -> PrimingCampaign:
        payload = dict(data)
        # Бэкфилл trigger_actions из одиночной колонки — CHECK требует
        # непустой массив (см. campaign.py и миграцию 0046).
        actions = payload.get("trigger_actions")
        if not actions:
            single = payload.get("trigger_action")
            if single is not None:
                payload["trigger_actions"] = [single]
        campaign = PrimingCampaign(**payload)
        return self._add(campaign)

    def update(
        self, id_: int, data: Mapping[str, Any]
    ) -> Optional[PrimingCampaign]:
        campaign = self.get(id_)
        if campaign is None:
            return None
        for field, value in data.items():
            setattr(campaign, field, value)
        self.session.flush()
        return campaign

    def set_status(self, id_: int, status: str) -> Optional[PrimingCampaign]:
        return self.update(id_, {"status": status})

    def delete_hard(self, id_: int) -> bool:
        campaign = self.get(id_)
        if campaign is None:
            return False
        self.session.delete(campaign)
        self.session.flush()
        return True
