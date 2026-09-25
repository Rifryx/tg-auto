"""Репозиторий чёрного списка каналов кампании."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sqlalchemy import and_, or_, select

from core.repositories.base import BaseRepository
from modules.shilling.models import ShillingBlacklist

if TYPE_CHECKING:  # pragma: no cover
    from modules.shilling.schemas.blacklist import BlacklistCreate


class BlacklistRepository(BaseRepository[ShillingBlacklist]):
    model = ShillingBlacklist

    def list_by_campaign(self, campaign_id: int) -> list[ShillingBlacklist]:
        stmt = (
            select(ShillingBlacklist)
            .where(ShillingBlacklist.campaign_id == campaign_id)
            .order_by(ShillingBlacklist.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars())

    def is_blacklisted(
        self,
        campaign_id: int,
        *,
        chat_id: Optional[int] = None,
        username: Optional[str] = None,
    ) -> bool:
        """Проверка перед постингом. Хотя бы один из идентификаторов должен
        быть задан — иначе False (нечего проверять)."""
        if chat_id is None and not username:
            return False
        clauses = []
        if chat_id is not None:
            clauses.append(ShillingBlacklist.chat_id == chat_id)
        if username:
            clauses.append(ShillingBlacklist.username == username.lstrip("@"))
        stmt = select(ShillingBlacklist.id).where(
            and_(
                ShillingBlacklist.campaign_id == campaign_id,
                or_(*clauses),
            )
        ).limit(1)
        return self.session.execute(stmt).scalars().first() is not None

    def find(
        self,
        campaign_id: int,
        *,
        chat_id: Optional[int] = None,
        username: Optional[str] = None,
    ) -> Optional[ShillingBlacklist]:
        if chat_id is None and not username:
            return None
        clauses = []
        if chat_id is not None:
            clauses.append(ShillingBlacklist.chat_id == chat_id)
        if username:
            clauses.append(ShillingBlacklist.username == username.lstrip("@"))
        stmt = select(ShillingBlacklist).where(
            ShillingBlacklist.campaign_id == campaign_id
        ).where(or_(*clauses))
        return self.session.execute(stmt).scalars().first()

    def create(
        self,
        campaign_id: int,
        data: "BlacklistCreate",
        *,
        auto: bool = False,
    ) -> ShillingBlacklist:
        payload = data.model_dump(exclude_unset=True)
        username = payload.get("username")
        if username:
            username = username.lstrip("@")
        entry = ShillingBlacklist(
            campaign_id=campaign_id,
            chat_id=payload.get("chat_id"),
            username=username or None,
            reason=payload.get("reason"),
            auto=auto,
        )
        return self._add(entry)

    def delete(self, campaign_id: int, entry_id: int) -> bool:
        obj = self.get(entry_id)
        if obj is None or obj.campaign_id != campaign_id:
            return False
        self.session.delete(obj)
        self.session.flush()
        return True
