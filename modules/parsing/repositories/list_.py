"""Репозиторий ParsedList."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from sqlalchemy import select

from core.repositories.base import BaseRepository
from modules.parsing.models import ParsedList


class ParsedListRepository(BaseRepository[ParsedList]):
    model = ParsedList

    def get_by_id(self, id_: int) -> Optional[ParsedList]:
        return self.get(id_)

    def list_by_owner(self, owner_user_id: int) -> list[ParsedList]:
        stmt = (
            select(ParsedList)
            .where(ParsedList.owner_user_id == owner_user_id)
            .order_by(ParsedList.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars())

    def create(self, data: Mapping[str, Any]) -> ParsedList:
        obj = ParsedList(**dict(data))
        return self._add(obj)

    def update(
        self, id_: int, data: Mapping[str, Any]
    ) -> Optional[ParsedList]:
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
