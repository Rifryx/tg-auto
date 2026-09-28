"""Репозиторий blacklist.

Ключевая операция — :meth:`match`: быстрый lookup «попадает ли цель в
чёрный список пользователя или в глобальный». Используется парсером
(промпт 3.2) и импортом целей (2.5).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from sqlalchemy import or_, select, text

from core.repositories.base import BaseRepository
from modules.priming.models import PrimingBlacklist


# Скользящее окно кросс-модульного blacklist'а. За пределами окна
# старые пометки не блокируют цель — пользователи меняют настройки
# приватности, поэтому вечный бан по умолчанию не ставим.
CROSS_MODULE_WINDOW_DAYS = 7


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

    def match_cross_module(
        self,
        owner_user_id: Optional[int],
        *,
        tg_user_id: Optional[int] = None,
        username: Optional[str] = None,
        phone: Optional[str] = None,
        window_days: int = CROSS_MODULE_WINDOW_DAYS,
        now: Optional[datetime] = None,
    ) -> Optional[dict]:
        """Проверяет ``core.blacklist_all`` — user-level blacklist по всем
        модулям в скользящем окне ``window_days``. Возвращает первую
        совпавшую запись в виде dict (module/id/reason/added_at) или None.
        """
        if tg_user_id is None and username is None and phone is None:
            return None
        now = now or datetime.now(timezone.utc)
        cutoff = now - timedelta(days=window_days)

        # WHERE строим динамически: psycopg + prepared statements не выводят
        # тип NULL-параметра в ветке ``$n IS NOT NULL`` (AmbiguousParameter),
        # поэтому не отправляем то, что не задано.
        key_clauses: list[str] = []
        params: dict[str, object] = {"cutoff": cutoff, "owner": owner_user_id}
        if tg_user_id is not None:
            key_clauses.append("tg_user_id = :tg")
            params["tg"] = tg_user_id
        if username is not None:
            key_clauses.append("username = :username")
            params["username"] = username
        if phone is not None:
            key_clauses.append("phone = :phone")
            params["phone"] = phone

        if owner_user_id is None:
            owner_filter = "owner_user_id IS NULL"
            params.pop("owner", None)
        else:
            owner_filter = "(owner_user_id IS NULL OR owner_user_id = :owner)"

        stmt = text(
            f"""
            SELECT module, id, owner_user_id, tg_user_id, username, phone,
                   reason, added_at
            FROM core.blacklist_all
            WHERE added_at >= :cutoff
              AND {owner_filter}
              AND ({' OR '.join(key_clauses)})
            LIMIT 1
            """
        )
        row = self.session.execute(stmt, params).mappings().first()
        return dict(row) if row is not None else None
