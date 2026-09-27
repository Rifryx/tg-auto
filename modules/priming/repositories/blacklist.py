"""Репозиторий blacklist.

Ключевая операция — :meth:`match`: быстрый lookup «попадает ли цель в
чёрный список пользователя или в глобальный». Используется парсером
(промпт 3.2) и импортом целей (2.5).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from sqlalchemy import or_, select

from core.repositories.base import BaseRepository
from modules.priming.models import PrimingBlacklist


class BlacklistRepository(BaseRepository[PrimingBlacklist]):
    model = PrimingBlacklist

    def get_by_id(self, id_: int) -> Optional[PrimingBlacklist]:
        return self.get(id_)

    def list_by_owner(
        self, owner_user_id: Optional[int]
    ) -> list[PrimingBlacklist]:
        stmt = select(PrimingBlacklist).where(
            PrimingBlacklist.owner_user_id.is_(owner_user_id)
            if owner_user_id is None
            else PrimingBlacklist.owner_user_id == owner_user_id
        )
        return list(self.session.execute(stmt).scalars())

    def create(self, data: Mapping[str, Any]) -> PrimingBlacklist:
        obj = PrimingBlacklist(**dict(data))
        return self._add(obj)

    def bulk_add(
        self,
        owner_user_id: Optional[int],
        rows: list[Mapping[str, Any]],
        *,
        default_reason: str,
    ) -> int:
        """Массовое добавление; возвращает число вставленных строк."""
        if not rows:
            return 0
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        payload = []
        for row in rows:
            item = dict(row)
            item.setdefault("owner_user_id", owner_user_id)
            item.setdefault("reason", default_reason)
            payload.append(item)
        stmt = pg_insert(PrimingBlacklist).values(payload)
        # Нет уникального индекса, дублей не отбрасываем — ответственность
        # за дедуп на вызывающем; здесь просто вставляем.
        result = self.session.execute(stmt)
        self.session.flush()
        return result.rowcount

    def delete_hard(self, id_: int) -> bool:
        obj = self.get(id_)
        if obj is None:
            return False
        self.session.delete(obj)
        self.session.flush()
        return True

    def match(
        self,
        owner_user_id: Optional[int],
        *,
        tg_user_id: Optional[int] = None,
        username: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> Optional[PrimingBlacklist]:
        """Возвращает первую совпадающую запись blacklist'а.

        Совпадение по любому из ``tg_user_id / username / phone``. Область
        поиска — записи ``owner_user_id`` пользователя + глобальные
        (``owner_user_id IS NULL``).
        """
        conditions = []
        if tg_user_id is not None:
            conditions.append(PrimingBlacklist.tg_user_id == tg_user_id)
        if username is not None:
            conditions.append(PrimingBlacklist.username == username)
        if phone is not None:
            conditions.append(PrimingBlacklist.phone == phone)
        if not conditions:
            return None
        # Владелец: свой или глобальный.
        owner_filter = or_(
            PrimingBlacklist.owner_user_id.is_(None),
            PrimingBlacklist.owner_user_id == owner_user_id,
        )
        stmt = (
            select(PrimingBlacklist)
            .where(owner_filter, or_(*conditions))
            .limit(1)
        )
        return self.session.execute(stmt).scalars().first()
