"""Роутер модуля НейроШиллинг.

Префикс ``/modules/shilling``. Тут — только CRUD кампаний (промпт 2.1);
сценарии/роли/шаги, аккаунты, цели, ЧС, readiness/stats/start/stop
подключаются следующими промптами (2.2–2.4).

Монтирование — в ``api/routing.py`` (единственный список роутеров).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from modules.shilling.repositories import CampaignRepository
from modules.shilling.schemas import CampaignCreate, CampaignRead, CampaignUpdate

router = APIRouter(
    prefix="/modules/shilling",
    tags=["shilling"],
    dependencies=[Depends(require_user)],
)


# --- Кампании (CRUD) --------------------------------------------------------


@router.get("/campaigns", response_model=list[CampaignRead])
def list_campaigns(session: Session = Depends(get_session)) -> list[CampaignRead]:
    """Список кампаний, свежие сверху (сортировка репозитория)."""
    return [CampaignRead.model_validate(c) for c in CampaignRepository(session).list_all()]


@router.get("/campaigns/{campaign_id}", response_model=CampaignRead)
def get_campaign(
    campaign_id: int, session: Session = Depends(get_session)
) -> CampaignRead:
    campaign = CampaignRepository(session).get(campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    return CampaignRead.model_validate(campaign)


@router.post(
    "/campaigns",
    response_model=CampaignRead,
    status_code=status.HTTP_201_CREATED,
    # Лимит плана (shilling_campaigns_active_max) добавится в промпте 8.5;
    # пока без enforce_limit — фичи-ключа для шиллинга ещё нет в billing.
)
def create_campaign(
    body: CampaignCreate,
    session: Session = Depends(get_session),
) -> CampaignRead:
    campaign = CampaignRepository(session).create(body)
    session.commit()
    return CampaignRead.model_validate(campaign)


@router.patch("/campaigns/{campaign_id}", response_model=CampaignRead)
def patch_campaign(
    campaign_id: int,
    body: CampaignUpdate,
    session: Session = Depends(get_session),
) -> CampaignRead:
    campaign = CampaignRepository(session).update(campaign_id, body)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    session.commit()
    return CampaignRead.model_validate(campaign)


@router.delete(
    "/campaigns/{campaign_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def delete_campaign(
    campaign_id: int,
    session: Session = Depends(get_session),
) -> None:
    repo = CampaignRepository(session)
    campaign = repo.get(campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    # Мягкий отказ на running: пусть пользователь сначала остановит через /stop,
    # чтобы избежать гонки с воркером (задачи в полёте могут писать в логи).
    if campaign.status == "running":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"campaign {campaign_id} is running; stop it before deleting",
        )
    repo.delete(campaign_id)
    session.commit()
