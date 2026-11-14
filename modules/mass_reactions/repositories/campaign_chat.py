"""Репозиторий чатов кампании масс-реакций."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

from sqlalchemy import func, select, update

from core.repositories.base import BaseRepository
from modules.mass_reactions.models import MassReactionCampaignChat
from modules.mass_reactions.schemas.enums import ChatState


class CampaignChatRepository(BaseRepository[MassReactionCampaignChat]):
    model = MassReactionCampaignChat

    def list_by_campaign(self, campaign_id: int) -> list[MassReactionCampaignChat]:
        stmt = (
            select(MassReactionCampaignChat)
            .where(MassReactionCampaignChat.campaign_id == campaign_id)
            .order_by(MassReactionCampaignChat.id)
        )
        return list(self.session.execute(stmt).scalars())

    def create(self, data: Mapping[str, Any]) -> MassReactionCampaignChat:
        return self._add(MassReactionCampaignChat(**dict(data)))

    def update(
        self, id_: int, data: Mapping[str, Any]
    ) -> Optional[MassReactionCampaignChat]:
        obj = self.get(id_)
        if obj is None:
            return None
        for k, v in data.items():
            setattr(obj, k, v)
        self.session.flush()
        return obj

    def bump_counter(self, chat_id: int) -> int:
        """Атомарно +1 к счётчику чата, возвращает НОВОЕ значение.

        Это и есть ``increment_counter`` для слушателя: «каждое N-е» считается
        по чату, поэтому инкремент должен быть атомарным (несколько сообщений
        могут прийти параллельно).
        """
        stmt = (
            update(MassReactionCampaignChat)
            .where(MassReactionCampaignChat.id == chat_id)
            .values(reaction_counter=MassReactionCampaignChat.reaction_counter + 1)
            .returning(MassReactionCampaignChat.reaction_counter)
        )
        row = self.session.execute(stmt).scalar_one_or_none()
        return int(row) if row is not None else 0

    def mark_reacted(self, chat_id: int, *, when: datetime) -> None:
        stmt = (
            update(MassReactionCampaignChat)
            .where(MassReactionCampaignChat.id == chat_id)
            .values(
                reactions_total=MassReactionCampaignChat.reactions_total + 1,
                last_reacted_at=when,
            )
        )
        self.session.execute(stmt)

    def list_unassigned(self, campaign_id: int) -> list[MassReactionCampaignChat]:
        """Чаты кампании без закреплённого аккаунта (ждут раскладки tick'ом)."""
        stmt = select(MassReactionCampaignChat).where(
            MassReactionCampaignChat.campaign_id == campaign_id,
            MassReactionCampaignChat.account_id.is_(None),
            MassReactionCampaignChat.state.in_(
                (ChatState.PENDING.value, ChatState.ACTIVE.value)
            ),
        )
        return list(self.session.execute(stmt).scalars())

    def count_by_account(self, campaign_id: int) -> dict[int, int]:
        """Сколько чатов закреплено за каждым аккаунтом в кампании."""
        stmt = (
            select(MassReactionCampaignChat.account_id, func.count())
            .where(
                MassReactionCampaignChat.campaign_id == campaign_id,
                MassReactionCampaignChat.account_id.is_not(None),
            )
            .group_by(MassReactionCampaignChat.account_id)
        )
        return {int(aid): int(cnt) for aid, cnt in self.session.execute(stmt).all()}

    def assign_account(self, chat_id: int, account_id: int) -> None:
        stmt = (
            update(MassReactionCampaignChat)
            .where(MassReactionCampaignChat.id == chat_id)
            .values(account_id=account_id, state=ChatState.ACTIVE.value)
        )
        self.session.execute(stmt)
