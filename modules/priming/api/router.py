"""Роутер модуля прайминга (промпт 2.4).

Префикс ``/modules/priming``. На этом промпте — CRUD кампаний и
lifecycle-переходы (start / pause / resume / stop). Аккаунты/цели/
парсер/пейволл — на промптах 2.5 и далее.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.queue import get_task_queue
from core.queue import TaskQueue
from modules.priming.api import service
from modules.priming.repositories import CampaignRepository
from modules.priming.schemas import (
    PrimingCampaignCreate,
    PrimingCampaignRead,
    PrimingCampaignStatus,
    PrimingCampaignUpdate,
)


router = APIRouter(
    prefix="/modules/priming",
    tags=["priming"],
    dependencies=[Depends(require_user)],
)


def _raise(exc: service.ServiceError):
    raise HTTPException(
        status_code=exc.status_code,
        detail={"error": exc.code, "message": str(exc)},
    )


# ---------------------------------------------------------------------------
# Кампании — CRUD
# ---------------------------------------------------------------------------

@router.get("/campaigns", response_model=list[PrimingCampaignRead])
def list_campaigns(session: Session = Depends(get_session)):
    return [
        PrimingCampaignRead.model_validate(c)
        for c in CampaignRepository(session).list_all()
    ]


@router.get("/campaigns/{campaign_id}", response_model=PrimingCampaignRead)
def get_campaign(campaign_id: int, session: Session = Depends(get_session)):
    try:
        campaign = service.get_campaign(session, campaign_id)
    except service.ServiceError as exc:
        _raise(exc)
    return PrimingCampaignRead.model_validate(campaign)


@router.post(
    "/campaigns",
    response_model=PrimingCampaignRead,
    status_code=status.HTTP_201_CREATED,
)
def create_campaign(
    body: PrimingCampaignCreate,
    session: Session = Depends(get_session),
    user_id: str = Depends(require_user),
):
    data = body.model_dump()
    if data.get("created_by") is None:
        # user_id из require_user — строка (uuid); в БД BigInteger.
        # Пытаемся привести к int, иначе оставляем None.
        try:
            data["created_by"] = int(user_id)
        except (TypeError, ValueError):
            data["created_by"] = None
    campaign = service.create_campaign(session, data)
    session.commit()
    return PrimingCampaignRead.model_validate(campaign)


@router.patch("/campaigns/{campaign_id}", response_model=PrimingCampaignRead)
def update_campaign(
    campaign_id: int,
    body: PrimingCampaignUpdate,
    session: Session = Depends(get_session),
):
    try:
        campaign = service.update_campaign(
            session, campaign_id, body.model_dump(exclude_unset=True),
        )
    except service.ServiceError as exc:
        _raise(exc)
    session.commit()
    return PrimingCampaignRead.model_validate(campaign)


@router.delete("/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_campaign(campaign_id: int, session: Session = Depends(get_session)):
    try:
        service.delete_campaign(session, campaign_id)
    except service.ServiceError as exc:
        _raise(exc)
    session.commit()
    return None


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@router.post("/campaigns/{campaign_id}/start", response_model=PrimingCampaignRead)
async def start_campaign(
    campaign_id: int,
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
):
    try:
        campaign = await service.start_campaign(session, campaign_id, task_queue)
    except service.ServiceError as exc:
        _raise(exc)
    return PrimingCampaignRead.model_validate(campaign)


@router.post("/campaigns/{campaign_id}/pause", response_model=PrimingCampaignRead)
def pause_campaign(campaign_id: int, session: Session = Depends(get_session)):
    try:
        campaign = service.pause_campaign(session, campaign_id)
    except service.ServiceError as exc:
        _raise(exc)
    session.commit()
    return PrimingCampaignRead.model_validate(campaign)


@router.post("/campaigns/{campaign_id}/resume", response_model=PrimingCampaignRead)
async def resume_campaign(
    campaign_id: int,
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
):
    try:
        campaign = await service.resume_campaign(session, campaign_id, task_queue)
    except service.ServiceError as exc:
        _raise(exc)
    return PrimingCampaignRead.model_validate(campaign)


@router.post("/campaigns/{campaign_id}/stop", response_model=PrimingCampaignRead)
def stop_campaign(campaign_id: int, session: Session = Depends(get_session)):
    try:
        campaign = service.stop_campaign(session, campaign_id)
    except service.ServiceError as exc:
        _raise(exc)
    session.commit()
    return PrimingCampaignRead.model_validate(campaign)
