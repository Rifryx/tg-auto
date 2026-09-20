"""CRUD media-хранилища (этап 9, backlog #1).

Файл загружается multipart-ом, ответ отдаёт id и sha256 (дедуп: одна и та
же картинка не хранится дважды у одного пользователя). Скачивание байтов
наружу не отдаётся — media используется только внутренними actions.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from core.repositories.media_asset import MediaAssetRepository

router = APIRouter(
    prefix="/media-assets",
    tags=["media-assets"],
    dependencies=[Depends(require_user)],
)

# Хард-лимит: не даём заливать в БД чудовища. Для видео поднимаем позже.
_MAX_BYTES = 25 * 1024 * 1024


class MediaAssetRead(BaseModel):
    id: int
    mime: str
    size_bytes: int
    sha256: str
    filename: str | None
    created_at: datetime


def _serialize(obj) -> MediaAssetRead:
    return MediaAssetRead(
        id=obj.id,
        mime=obj.mime,
        size_bytes=obj.size_bytes,
        sha256=obj.sha256,
        filename=obj.filename,
        created_at=obj.created_at,
    )


@router.get("", response_model=list[MediaAssetRead])
def list_media(
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    return [_serialize(a) for a in MediaAssetRepository(session).list_for_user(user_id)]


@router.post("", response_model=MediaAssetRead, status_code=status.HTTP_201_CREATED)
async def upload_media(
    file: UploadFile = File(...),
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    blob = await file.read()
    if not blob:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "empty file")
    if len(blob) > _MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"file too large: {len(blob)} > {_MAX_BYTES}",
        )

    obj = MediaAssetRepository(session).get_or_create(
        user_id=user_id,
        blob=blob,
        mime=file.content_type or "application/octet-stream",
        filename=file.filename,
    )
    session.commit()
    return _serialize(obj)


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_media(
    asset_id: int,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    repo = MediaAssetRepository(session)
    obj = repo.get(asset_id)
    if obj is None or obj.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "media asset not found")
    repo.delete(asset_id)
    session.commit()
    return None
