"""Репозиторий key-value настроек приложения (app_settings)."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from core.models.app_setting import AppSetting


class AppSettingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, key: str) -> Optional[dict]:
        row = self.session.execute(
            select(AppSetting).where(AppSetting.key == key)
        ).scalar_one_or_none()
        return dict(row.value) if row is not None else None

    def set(self, key: str, value: dict, *, updated_by: Optional[str] = None) -> None:
        stmt = pg_insert(AppSetting).values(
            key=key, value=value, updated_by=updated_by
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": stmt.excluded.value, "updated_by": stmt.excluded.updated_by},
        )
        self.session.execute(stmt)
