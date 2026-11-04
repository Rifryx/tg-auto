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

    def count_by_list(self, list_id: int) -> int:
        from sqlalchemy import func

        return int(
            self.session.execute(
                select(func.count())
                .select_from(ParsedCommunityItem)
                .where(ParsedCommunityItem.list_id == list_id)
            ).scalar_one()
        )

    def delete_items(self, list_id: int, item_ids: list[int]) -> int:
        """Удаляет указанные сообщества из списка. Возвращает число удалённых.

        Жалоба: «толку от этих каналов в коллекции, если их нельзя... удалить
        оттуда» — ``item_ids`` ограничиваем ``list_id``, чтобы нельзя было
        задеть чужой список (как и ``ParsedListTargetRepository.delete_targets``)."""
        if not item_ids:
            return 0
        from sqlalchemy import delete as sa_delete

        result = self.session.execute(
            sa_delete(ParsedCommunityItem).where(
                ParsedCommunityItem.list_id == list_id,
                ParsedCommunityItem.id.in_(item_ids),
            )
        )
        self.session.flush()
        return int(result.rowcount or 0)

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
