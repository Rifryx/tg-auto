"""Репозиторий проектов (этап 2)."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from core.models.project import Project
from core.repositories.base import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    model = Project

    def create(self, *, user_id: str, name: str, description: Optional[str] = None) -> Project:
        return self._add(Project(user_id=user_id, name=name, description=description))

    def list_for_user(self, user_id: str) -> list[Project]:
        stmt = (
            select(Project)
            .where(Project.user_id == user_id)
            .order_by(Project.created_at.desc())
        )
        return list(self.session.execute(stmt).scalars().all())

    def update(
        self,
        project_id: int,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[Project]:
        obj = self.get(project_id)
        if obj is None:
            return None
        if name is not None:
            obj.name = name
        if description is not None:
            obj.description = description
        self.session.flush()
        return obj

    def delete(self, project_id: int) -> bool:
        obj = self.get(project_id)
        if obj is None:
            return False
        self.session.delete(obj)
        self.session.flush()
        return True
