"""Репозиторий ParsedListTarget."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from sqlalchemy import select

from core.repositories.base import BaseRepository
from modules.parsing.models import ParsedListTarget


class ParsedListTargetRepository(BaseRepository[ParsedListTarget]):
    model = ParsedListTarget

    def list_by_list(
        self, list_id: int, *, limit: Optional[int] = None, offset: int = 0,
    ) -> list[ParsedListTarget]:
        stmt = (
            select(ParsedListTarget)
            .where(ParsedListTarget.list_id == list_id)
            .order_by(ParsedListTarget.id.asc())
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        return list(self.session.execute(stmt).scalars())

    def bulk_create(
        self, list_id: int, rows: list[Mapping[str, Any]]
    ) -> int:
        """Дедуп через ON CONFLICT DO NOTHING по (list_id, tg_user_id).

        RETURNING id — иначе psycopg отдаёт rowcount=-1 для
        INSERT ... ON CONFLICT DO NOTHING без RETURNING.
        """
        if not rows:
            return 0
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        payload = []
        for row in rows:
            item = dict(row)
            item["list_id"] = list_id
            item.setdefault("last_seen_bucket", "unknown")
            payload.append(item)
        stmt = (
            pg_insert(ParsedListTarget)
            .values(payload)
            .on_conflict_do_nothing(index_elements=["list_id", "tg_user_id"])
            .returning(ParsedListTarget.id)
        )
        inserted = list(self.session.execute(stmt).scalars())
        self.session.flush()
        return len(inserted)

    def count_by_list(self, list_id: int) -> int:
        from sqlalchemy import func

        return int(
            self.session.execute(
                select(func.count())
                .select_from(ParsedListTarget)
                .where(ParsedListTarget.list_id == list_id)
            ).scalar_one()
        )

    def delete_targets(self, list_id: int, target_ids: list[int]) -> int:
        """Удаляет указанные строки списка. Возвращает число удалённых.

        Жалоба: «в базе нет возможности удалять спаршеных». ``target_ids``
        ограничиваем ``list_id``, чтобы нельзя было задеть чужой список."""
        if not target_ids:
            return 0
        from sqlalchemy import delete as sa_delete

        result = self.session.execute(
            sa_delete(ParsedListTarget).where(
                ParsedListTarget.list_id == list_id,
                ParsedListTarget.id.in_(target_ids),
            )
        )
        self.session.flush()
        return int(result.rowcount or 0)
