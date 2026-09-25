"""Репозиторий целевых каналов кампании шиллинга."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sqlalchemy import select

from core.repositories.base import BaseRepository
from modules.shilling.models import ShillingTarget

if TYPE_CHECKING:  # pragma: no cover
    from modules.shilling.schemas.campaign_target import TargetCreate


class CampaignTargetRepository(BaseRepository[ShillingTarget]):
    model = ShillingTarget

    def list_by_campaign(self, campaign_id: int) -> list[ShillingTarget]:
        stmt = (
            select(ShillingTarget)
            .where(ShillingTarget.campaign_id == campaign_id)
            .order_by(ShillingTarget.created_at.asc())
        )
        return list(self.session.execute(stmt).scalars())

    def list_pending(self, campaign_id: int) -> list[ShillingTarget]:
        """Цели, ещё не резолвнутые (для воркера-резолвера)."""
        stmt = select(ShillingTarget).where(
            ShillingTarget.campaign_id == campaign_id,
            ShillingTarget.status == "pending",
        )
        return list(self.session.execute(stmt).scalars())

    def find_by_raw(self, campaign_id: int, raw_input: str) -> Optional[ShillingTarget]:
        stmt = select(ShillingTarget).where(
            ShillingTarget.campaign_id == campaign_id,
            ShillingTarget.raw_input == raw_input,
        )
        return self.session.execute(stmt).scalars().first()

    def create(self, campaign_id: int, data: "TargetCreate") -> ShillingTarget:
        payload = data.model_dump(exclude_unset=True)
        payload.pop("campaign_id", None)
        raw = payload.pop("raw_input").strip()
        target = ShillingTarget(
            campaign_id=campaign_id,
            raw_input=raw,
            kind=payload.get("kind", "username"),
        )
        return self._add(target)

    def mark_resolved(
        self, id_: int, *, resolved_chat_id: int, title: Optional[str] = None
    ) -> Optional[ShillingTarget]:
        target = self.get(id_)
        if target is None:
            return None
        target.resolved_chat_id = resolved_chat_id
        target.title = title
        target.status = "resolved"
        target.last_error = None
        self.session.flush()
        return target

    def mark_error(self, id_: int, error: str) -> Optional[ShillingTarget]:
        target = self.get(id_)
        if target is None:
            return None
        target.status = "error"
        target.last_error = error
        self.session.flush()
        return target

    def delete(self, campaign_id: int, target_id: int) -> bool:
        obj = self.get(target_id)
        if obj is None or obj.campaign_id != campaign_id:
            return False
        self.session.delete(obj)
        self.session.flush()
        return True
