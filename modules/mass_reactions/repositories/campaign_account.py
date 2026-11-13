"""Репозиторий аккаунтов-инициаторов кампании масс-реакций."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

from sqlalchemy import select, update

from core.repositories.base import BaseRepository
from modules.mass_reactions.models import MassReactionCampaignAccount
from modules.mass_reactions.schemas.enums import MassReactionAccountState


class CampaignAccountRepository(BaseRepository[MassReactionCampaignAccount]):
    model = MassReactionCampaignAccount

    def list_by_campaign(
        self, campaign_id: int
    ) -> list[MassReactionCampaignAccount]:
        stmt = (
            select(MassReactionCampaignAccount)
            .where(MassReactionCampaignAccount.campaign_id == campaign_id)
            .order_by(MassReactionCampaignAccount.id)
        )
        return list(self.session.execute(stmt).scalars())

    def list_available(
        self, campaign_id: int
    ) -> list[MassReactionCampaignAccount]:
        """Аккаунты, пригодные под закрепление чатов (не карантин/не выключены)."""
        stmt = select(MassReactionCampaignAccount).where(
            MassReactionCampaignAccount.campaign_id == campaign_id,
            MassReactionCampaignAccount.state.not_in(
                (
                    MassReactionAccountState.QUARANTINED.value,
                    MassReactionAccountState.DISABLED.value,
                )
            ),
        )
        return list(self.session.execute(stmt).scalars())

    def create(self, data: Mapping[str, Any]) -> MassReactionCampaignAccount:
        return self._add(MassReactionCampaignAccount(**dict(data)))

    def update(
        self, id_: int, data: Mapping[str, Any]
    ) -> Optional[MassReactionCampaignAccount]:
        obj = self.get(id_)
        if obj is None:
            return None
        for k, v in data.items():
            setattr(obj, k, v)
        self.session.flush()
        return obj

    def register_reaction(self, id_: int, *, when: datetime) -> None:
        """Инкремент счётчиков после успешной реакции."""
        stmt = (
            update(MassReactionCampaignAccount)
            .where(MassReactionCampaignAccount.id == id_)
            .values(
                reactions_today=MassReactionCampaignAccount.reactions_today + 1,
                reactions_total=MassReactionCampaignAccount.reactions_total + 1,
                last_reaction_at=when,
                flood_waits_consecutive=0,
            )
        )
        self.session.execute(stmt)

    def reset_daily_counters(self, campaign_id: int) -> int:
        stmt = (
            update(MassReactionCampaignAccount)
            .where(MassReactionCampaignAccount.campaign_id == campaign_id)
            .values(reactions_today=0)
        )
        return self.session.execute(stmt).rowcount
