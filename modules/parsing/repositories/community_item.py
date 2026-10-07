"""Репозиторий ParsedCommunityItem (Discovery сообществ, этап 2)."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from sqlalchemy import select

from core.repositories.base import BaseRepository
from modules.parsing.models import ParsedCommunityItem


class ParsedCommunityItemRepository(BaseRepository[ParsedCommunityItem]):
    model = ParsedCommunityItem

    def list_by_list(
        self, list_id: int, *, limit: Optional[int] = None, offset: int = 0,
    ) -> list[ParsedCommunityItem]:
        stmt = (
            select(ParsedCommunityItem)
            .where(ParsedCommunityItem.list_id == list_id)
            .order_by(ParsedCommunityItem.participants_count.desc().nullslast(),
                      ParsedCommunityItem.id.asc())
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        return list(self.session.execute(stmt).scalars())

    def bulk_create(self, list_id: int, rows: list[Mapping[str, Any]]) -> int:
        """Дедуп через ON CONFLICT DO NOTHING по (list_id, input_ref)."""
        if not rows:
            return 0
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        payload = [{**dict(r), "list_id": list_id} for r in rows]
        stmt = (
            pg_insert(ParsedCommunityItem)
            .values(payload)
            .on_conflict_do_nothing(index_elements=["list_id", "input_ref"])
            .returning(ParsedCommunityItem.id)
        )
        inserted = list(self.session.execute(stmt).scalars())
        self.session.flush()
        return len(inserted)
