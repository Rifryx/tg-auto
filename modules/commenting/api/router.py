"""Роутер модуля commenting (PROJECT-STAGES §1.2, §10).

Префикс ``/modules/commenting``. Смена статуса аккаунтов — только через
state machine (см. :mod:`modules.commenting.api.service`).

Монтирование (одной строкой в ``api/main.py``)::

    from modules.commenting.api import router as commenting_router
    app.include_router(commenting_router)
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.queue import get_publisher
from core.enums import CommentStatus
from core.queue.publisher import Publisher
from modules.commenting.api import service
from modules.commenting.repositories import (
    CampaignAccountRepository,
    CampaignRepository,
    CommentLogRepository,
)
from modules.commenting.worker.registry import (
    ACTION_ATTACH,
    ACTION_DETACH,
    publish_campaign_lifecycle,
)
from modules.commenting.schemas import (
    AttachAccountRequest,
    CampaignAccountRead,
    CampaignCreate,
    CampaignRead,
    CampaignUpdate,
    CommentLogRead,
)

router = APIRouter(
    prefix="/modules/commenting",
    tags=["commenting"],
    dependencies=[Depends(require_user)],
)


# --- Кампании (CRUD) ---------------------------------------------------------


@router.get("/campaigns", response_model=list[CampaignRead])
def list_campaigns(session: Session = Depends(get_session)) -> list[CampaignRead]:
    return [CampaignRead.model_validate(c) for c in CampaignRepository(session).list_all()]


@router.get("/campaigns/{campaign_id}", response_model=CampaignRead)
def get_campaign(campaign_id: int, session: Session = Depends(get_session)) -> CampaignRead:
    campaign = CampaignRepository(session).get(campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    return CampaignRead.model_validate(campaign)


@router.post("/campaigns", response_model=CampaignRead, status_code=status.HTTP_201_CREATED)
def create_campaign(
    body: CampaignCreate, session: Session = Depends(get_session)
) -> CampaignRead:
    campaign = CampaignRepository(session).create(body)
    session.commit()
    return CampaignRead.model_validate(campaign)


@router.patch("/campaigns/{campaign_id}", response_model=CampaignRead)
def patch_campaign(
    campaign_id: int,
    body: CampaignUpdate,
    session: Session = Depends(get_session),
    publisher: Optional[Publisher] = Depends(get_publisher),
) -> CampaignRead:
    campaign = CampaignRepository(session).update(campaign_id, body)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    session.commit()
    # Смена enabled → динамика слушателя (attach/detach) без рестарта воркера.
    # Публикуем ПОСЛЕ commit'а: изменение уже зафиксировано в БД (аудит #4).
    if body.enabled is not None:
        publish_campaign_lifecycle(
            publisher,
            campaign_id,
            ACTION_ATTACH if campaign.enabled else ACTION_DETACH,
        )
    return CampaignRead.model_validate(campaign)


@router.delete("/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_campaign(
    campaign_id: int,
    session: Session = Depends(get_session),
    publisher: Optional[Publisher] = Depends(get_publisher),
) -> None:
    if CampaignRepository(session).get(campaign_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    # detach публикуем ДО удаления записи: слушатель должен сняться раньше, чем
    # исчезнет кампания, иначе handler может сработать по уже удалённой кампании
    # (порядок, не гонка — acceptance #3).
    publish_campaign_lifecycle(publisher, campaign_id, ACTION_DETACH)
    CampaignRepository(session).delete(campaign_id)
    session.commit()


# --- Аккаунты кампании (attach/detach) ---------------------------------------


@router.get("/campaigns/{campaign_id}/accounts", response_model=list[CampaignAccountRead])
def list_accounts(
    campaign_id: int, session: Session = Depends(get_session)
) -> list[CampaignAccountRead]:
    if CampaignRepository(session).get(campaign_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    links = CampaignAccountRepository(session).list_by_campaign(campaign_id)
    return [CampaignAccountRead.model_validate(link) for link in links]


@router.post(
    "/campaigns/{campaign_id}/accounts",
    response_model=CampaignAccountRead,
    status_code=status.HTTP_201_CREATED,
)
def attach_account(
    campaign_id: int,
    body: AttachAccountRequest,
    session: Session = Depends(get_session),
    publisher: Optional[Publisher] = Depends(get_publisher),
) -> CampaignAccountRead:
    try:
        link = service.attach_account(
            session, publisher, campaign_id, body.account_id, body.override_prompt
        )
    except service.CommentingNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except service.CommentingConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    # Первый аккаунт enabled-кампании: раньше подключать было нечем (слушатель
    # писал "no_account" warning) — теперь триггерим attach (аудит #4).
    links = CampaignAccountRepository(session).list_by_campaign(campaign_id)
    campaign = CampaignRepository(session).get(campaign_id)
    if len(links) == 1 and campaign is not None and campaign.enabled:
        publish_campaign_lifecycle(publisher, campaign_id, ACTION_ATTACH)
    return CampaignAccountRead.model_validate(link)


@router.delete(
    "/campaigns/{campaign_id}/accounts/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def detach_account(
    campaign_id: int,
    account_id: int,
    session: Session = Depends(get_session),
    publisher: Optional[Publisher] = Depends(get_publisher),
) -> None:
    try:
        service.detach_account(session, publisher, campaign_id, account_id)
    except service.CommentingNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except service.CommentingConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


# --- Логи комментариев -------------------------------------------------------


@router.get("/campaigns/{campaign_id}/logs", response_model=list[CommentLogRead])
def list_logs(
    campaign_id: int,
    status_filter: Optional[CommentStatus] = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
) -> list[CommentLogRead]:
    if CampaignRepository(session).get(campaign_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    logs = CommentLogRepository(session).list_by_campaign(
        campaign_id, status=status_filter, limit=limit, offset=offset
    )
    return [CommentLogRead.model_validate(log) for log in logs]
