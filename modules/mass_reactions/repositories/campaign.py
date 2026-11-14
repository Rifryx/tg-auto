"""Репозиторий кампаний масс-реакций."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from sqlalchemy import select

from core.repositories.base import BaseRepository
from modules.mass_reactions.models import MassReactionCampaign


class CampaignRepository(BaseRepository[MassReactionCampaign]):
    model = MassReactionCampaign

    def get_by_id(self, id_: int) -> Optional[MassReactionCampaign]:
        return self.get(id_)

    def list_all(self) -> list[MassReactionCampaign]:
        stmt = select(MassReactionCampaign).order_by(
            MassReactionCampaign.created_at.desc(), MassReactionCampaign.id.desc()
        )
        return list(self.session.execute(stmt).scalars())

    def list_by_status(self, status: str) -> list[MassReactionCampaign]:
        stmt = (
            select(MassReactionCampaign)
            .where(MassReactionCampaign.status == status)
            .order_by(MassReactionCampaign.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars())

    def create(self, data: Mapping[str, Any]) -> MassReactionCampaign:
        return self._add(MassReactionCampaign(**dict(data)))

    def update(
        self, id_: int, data: Mapping[str, Any]
    ) -> Optional[MassReactionCampaign]:
        obj = self.get(id_)
        if obj is None:
            return None
        for k, v in data.items():
            setattr(obj, k, v)
        self.session.flush()
        return obj

    def set_status(self, id_: int, status: str) -> Optional[MassReactionCampaign]:
        return self.update(id_, {"status": status})

    def delete_hard(self, id_: int) -> bool:
        obj = self.get(id_)
        if obj is None:
            return False
        self.session.delete(obj)
        self.session.flush()
        return True
