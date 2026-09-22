"""Репозиторий пула asset'ов профиля (этап 6, backlog #1)."""

from __future__ import annotations

import random
from typing import Optional

from sqlalchemy import select

from core.models.profile_asset import ProfileAsset
from core.repositories.base import BaseRepository


class ProfileAssetRepository(BaseRepository[ProfileAsset]):
    model = ProfileAsset

    def create(
        self,
        *,
        user_id: str,
        kind: str,
        value: Optional[str] = None,
        binary: Optional[bytes] = None,
        mime: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> ProfileAsset:
        obj = ProfileAsset(
            user_id=user_id,
            kind=kind,
            value=value,
            binary=binary,
            mime=mime,
            tags=list(tags or []),
        )
        return self._add(obj)

    def list_for_user(
        self, user_id: str, kind: Optional[str] = None
    ) -> list[ProfileAsset]:
        stmt = select(ProfileAsset).where(ProfileAsset.user_id == user_id)
        if kind is not None:
            stmt = stmt.where(ProfileAsset.kind == kind)
        stmt = stmt.order_by(ProfileAsset.created_at.desc())
        return list(self.session.execute(stmt).scalars().all())

    def delete(self, asset_id: int) -> bool:
        obj = self.get(asset_id)
        if obj is None:
            return False
        self.session.delete(obj)
        self.session.flush()
        return True

    def pick_random(
        self,
        *,
        kind: str,
        tags_any: Optional[list[str]] = None,
        rng: Optional[random.Random] = None,
    ) -> Optional[ProfileAsset]:
        """Случайный asset заданного kind с опц. фильтром «содержит любой тег».

        Пусть выбор идёт равномерно (без учёта used_count) — этого достаточно
        для MVP; более честную ротацию (min used_count) добавим по триггеру.
        """
        rng = rng or random.Random()
        stmt = select(ProfileAsset).where(ProfileAsset.kind == kind)
        if tags_any:
            # Postgres: `jsonb ?| text[]` — «содержит любой ключ/элемент
            # из массива». Приводим питон-list к text[] через cast(ARRAY).
            from sqlalchemy import String, cast
            from sqlalchemy.dialects.postgresql import ARRAY

            stmt = stmt.where(
                ProfileAsset.tags.op("?|")(cast(tags_any, ARRAY(String)))
            )
        candidates = list(self.session.execute(stmt).scalars().all())
        if not candidates:
            return None
        chosen = rng.choice(candidates)
        chosen.used_count = (chosen.used_count or 0) + 1
        self.session.flush()
        return chosen
