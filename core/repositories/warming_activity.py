from __future__ import annotations

from sqlalchemy import select

from core.models import WarmingActivity
from core.repositories.base import BaseRepository
from core.schemas.warming import WarmingActivityCreate


class WarmingActivityRepository(BaseRepository[WarmingActivity]):
    """Лента действий прогрева. По сути append-only (§5.1)."""

    model = WarmingActivity

    def create(self, data: WarmingActivityCreate) -> WarmingActivity:
        activity = WarmingActivity(**data.model_dump())
        return self._add(activity)

    def list_by_account(self, account_id: int, limit: int = 100) -> list[WarmingActivity]:
        stmt = (
            select(WarmingActivity)
            .where(WarmingActivity.account_id == account_id)
            .order_by(WarmingActivity.created_at.desc(), WarmingActivity.id.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars().all())
