"""Репозиторий media store (этап 9, backlog #1)."""

from __future__ import annotations

import hashlib
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.models.media_asset import MediaAsset
from core.repositories.base import BaseRepository


class MediaAssetRepository(BaseRepository[MediaAsset]):
    model = MediaAsset

    def get_or_create(
        self,
        *,
        user_id: str,
        blob: bytes,
        mime: str,
        filename: Optional[str] = None,
    ) -> MediaAsset:
        """Дедуп по (user_id, sha256): один и тот же файл сохраняем один раз."""
        digest = hashlib.sha256(blob).hexdigest()

        existing = self.session.execute(
            select(MediaAsset).where(
                MediaAsset.user_id == user_id,
                MediaAsset.sha256 == digest,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        obj = MediaAsset(
            user_id=user_id,
            mime=mime,
            bytes=blob,
            size_bytes=len(blob),
            sha256=digest,
            filename=filename,
        )
        return self._add(obj)

    def list_for_user(self, user_id: str) -> list[MediaAsset]:
        stmt = (
            select(MediaAsset)
            .where(MediaAsset.user_id == user_id)
            .order_by(MediaAsset.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def delete(self, asset_id: int) -> bool:
        obj = self.get(asset_id)
        if obj is None:
            return False
        self.session.delete(obj)
        self.session.flush()
        return True
