"""API-эндпоинты для проектов (этап 2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from api.deps.auth import require_user
from api.deps.db import get_session
from core.repositories.project import ProjectRepository
from core.repositories.project_channel import ProjectChannelRepository
from core.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate

router = APIRouter(
    prefix="/projects", tags=["projects"], dependencies=[Depends(require_user)]
)


@router.get("", response_model=list[ProjectRead])
def list_projects(
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    return ProjectRepository(session).list_for_user(user_id)


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    body: ProjectCreate,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    try:
        obj = ProjectRepository(session).create(
            user_id=user_id, name=body.name.strip(), description=body.description
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Проект с таким названием уже существует",
        )
    return obj


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: int,
    body: ProjectUpdate,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    repo = ProjectRepository(session)
    obj = repo.get(project_id)
    if obj is None or obj.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Проект не найден")
    try:
        updated = repo.update(
            project_id,
            name=body.name.strip() if body.name else None,
            description=body.description,
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Проект с таким названием уже существует",
        )
    return updated


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: int,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    repo = ProjectRepository(session)
    obj = repo.get(project_id)
    if obj is None or obj.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Проект не найден")
    # accounts.project_id → SET NULL по FK.
    repo.delete(project_id)
    session.commit()
    return None


class ProjectChannelRead(BaseModel):
    """Канал, созданный аккаунтом в рамках проекта (этап 8, backlog #3)."""

    id: int
    account_id: int
    project_id: Optional[int]
    channel_tg_id: int
    title: str
    username: Optional[str]
    is_megagroup: bool
    pinned_message_id: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/{project_id}/channels", response_model=list[ProjectChannelRead])
def list_project_channels(
    project_id: int,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    """Каналы, созданные bulk-action create_channel в рамках проекта."""
    project = ProjectRepository(session).get(project_id)
    if project is None or project.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Проект не найден")
    return ProjectChannelRepository(session).list_for_project(project_id)
