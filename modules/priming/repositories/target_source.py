"""Репозиторий источников аудитории (парсер / CSV / ручной ввод)."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from sqlalchemy import select

from core.repositories.base import BaseRepository
from modules.priming.models import PrimingTargetSource


class TargetSourceRepository(BaseRepository[PrimingTargetSource]):
    model = PrimingTargetSource

    def get_by_id(self, id_: int) -> Optional[PrimingTargetSource]:
        return self.get(id_)

    def list_by_campaign(
        self, campaign_id: int
    ) -> list[PrimingTargetSource]:
        stmt = (
            select(PrimingTargetSource)
            .where(PrimingTargetSource.campaign_id == campaign_id)
            .order_by(PrimingTargetSource.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars())

    def create(self, data: Mapping[str, Any]) -> PrimingTargetSource:
        obj = PrimingTargetSource(**dict(data))
        return self._add(obj)

    def update(
        self, id_: int, data: Mapping[str, Any]
    ) -> Optional[PrimingTargetSource]:
        obj = self.get(id_)
        if obj is None:
            return None
        for k, v in data.items():
            setattr(obj, k, v)
        self.session.flush()
        return obj

    def delete_hard(self, id_: int) -> bool:
        obj = self.get(id_)
        if obj is None:
            return False
        self.session.delete(obj)
        self.session.flush()
        return True
