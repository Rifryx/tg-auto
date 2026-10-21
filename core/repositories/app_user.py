"""Репозиторий кэша профилей пользователей Mini App (app_users)."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from core.models.app_user import AppUser


class AppUserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(
        self,
        user_id: str,
        *,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> None:
        """Записать/обновить профиль (идемпотентно, ON CONFLICT по user_id)."""
        stmt = pg_insert(AppUser).values(
            user_id=user_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[AppUser.user_id],
            set_={
                "username": stmt.excluded.username,
                "first_name": stmt.excluded.first_name,
                "last_name": stmt.excluded.last_name,
            },
        )
        self.session.execute(stmt)

    def find_by_username(self, username: str) -> Optional[AppUser]:
        """Найти пользователя по @username (без учёта регистра, ведущий @ — опц.).

        Username в Telegram регистронезависим и уникален, но кэш пишется по
        user_id best-effort, поэтому теоретически возможны устаревшие дубли —
        берём самый свежий по updated_at.
        """
        handle = (username or "").strip().lstrip("@")
        if not handle:
            return None
        from sqlalchemy import func

        row = self.session.execute(
            select(AppUser)
            .where(func.lower(AppUser.username) == handle.lower())
            .order_by(AppUser.updated_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        return row

    def get_many(self, user_ids: list[str]) -> dict[str, AppUser]:
        if not user_ids:
            return {}
        rows = self.session.execute(
            select(AppUser).where(AppUser.user_id.in_(user_ids))
        ).scalars()
        return {u.user_id: u for u in rows}
