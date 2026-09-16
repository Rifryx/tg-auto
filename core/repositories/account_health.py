from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.models import AccountHealth
from core.repositories.base import BaseRepository
from core.schemas.account_health import AccountHealthUpdate


class AccountHealthRepository(BaseRepository[AccountHealth]):
    model = AccountHealth

    def get_or_create(self, account_id: int) -> AccountHealth:
        obj = self.session.get(AccountHealth, account_id)
        if obj is not None:
            return obj
        # ON CONFLICT DO NOTHING — если параллельно уже создали (redis-задача).
        stmt = (
            pg_insert(AccountHealth)
            .values(account_id=account_id)
            .on_conflict_do_nothing(index_elements=["account_id"])
        )
        self.session.execute(stmt)
        self.session.flush()
        return self.session.get(AccountHealth, account_id)  # type: ignore[return-value]

    def get(self, account_id: int) -> Optional[AccountHealth]:  # type: ignore[override]
        return self.session.get(AccountHealth, account_id)

    def update(self, account_id: int, data: AccountHealthUpdate) -> AccountHealth:
        obj = self.get_or_create(account_id)
        payload = data.model_dump(exclude_unset=True)
        for field, value in payload.items():
            setattr(obj, field, value)
        self.session.flush()
        return obj

    def list_at_risk(self, max_score: int = 40, limit: int = 100) -> list[AccountHealth]:
        stmt = (
            select(AccountHealth)
            .where(AccountHealth.health_score <= max_score)
            .order_by(AccountHealth.health_score.asc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars().all())
