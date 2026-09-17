from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.models.ban_risk import BanRiskSnapshot
from core.repositories.base import BaseRepository


class BanRiskRepository(BaseRepository[BanRiskSnapshot]):
    model = BanRiskSnapshot

    def get(self, account_id: int) -> Optional[BanRiskSnapshot]:  # type: ignore[override]
        return self.session.get(BanRiskSnapshot, account_id)

    def get_or_create(self, account_id: int) -> BanRiskSnapshot:
        obj = self.get(account_id)
        if obj is not None:
            return obj
        stmt = (
            pg_insert(BanRiskSnapshot)
            .values(account_id=account_id)
            .on_conflict_do_nothing(index_elements=["account_id"])
        )
        self.session.execute(stmt)
        self.session.flush()
        return self.session.get(BanRiskSnapshot, account_id)  # type: ignore[return-value]

    def upsert(self, account_id: int, **fields) -> BanRiskSnapshot:
        obj = self.get_or_create(account_id)
        for k, v in fields.items():
            setattr(obj, k, v)
        self.session.flush()
        return obj

    def list_high_risk(
        self, min_score: float = 0.5, limit: int = 100
    ) -> list[BanRiskSnapshot]:
        stmt = (
            select(BanRiskSnapshot)
            .where(BanRiskSnapshot.risk_score >= min_score)
            .order_by(BanRiskSnapshot.risk_score.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars().all())
