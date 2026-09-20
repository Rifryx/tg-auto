"""CRUD пула asset'ов профиля (этап 6, backlog #1)."""

from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from core.repositories.profile_asset import ProfileAssetRepository
from core.schemas.profile_asset import ProfileAssetCreate, ProfileAssetRead

router = APIRouter(
    prefix="/profile-assets",
    tags=["profile-assets"],
    dependencies=[Depends(require_user)],
)


def _serialize(obj) -> ProfileAssetRead:
    return ProfileAssetRead(
        id=obj.id,
        kind=obj.kind,
        value=obj.value,
        mime=obj.mime,
        tags=list(obj.tags or []),
        used_count=obj.used_count or 0,
        created_at=obj.created_at,
        has_binary=obj.binary is not None,
    )


@router.get("", response_model=list[ProfileAssetRead])
def list_assets(
    kind: str | None = None,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    return [
        _serialize(a)
        for a in ProfileAssetRepository(session).list_for_user(user_id, kind=kind)
    ]


@router.post("", response_model=ProfileAssetRead, status_code=status.HTTP_201_CREATED)
def create_asset(
    body: ProfileAssetCreate,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    binary = None
    if body.binary_b64:
        try:
            binary = base64.b64decode(body.binary_b64, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"invalid base64 binary: {exc}",
            ) from exc

    obj = ProfileAssetRepository(session).create(
        user_id=user_id,
        kind=body.kind,
        value=body.value,
        binary=binary,
        mime=body.mime,
        tags=list(body.tags),
    )
    session.commit()
    return _serialize(obj)


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(
    asset_id: int,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
):
    repo = ProfileAssetRepository(session)
    obj = repo.get(asset_id)
    if obj is None or obj.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "asset not found")
    repo.delete(asset_id)
    session.commit()
    return None
