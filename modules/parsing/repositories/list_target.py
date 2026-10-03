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
