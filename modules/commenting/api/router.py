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
from api.deps.limits import enforce_limit
from api.deps.queue import get_publisher
from core.enums import CommentStatus
from core.queue.publisher import Publisher
from modules.commenting.api import service
from modules.commenting.repositories import (
    AccountPresetRepository,
    CampaignAccountRepository,
    CampaignRepository,
    CommentLogRepository,
    DelayPresetRepository,
)
from modules.commenting.worker.registry import (
    ACTION_ATTACH,
    ACTION_DETACH,
    publish_campaign_lifecycle,
)
from modules.commenting.schemas import (
    AccountPresetCreate,
    AccountPresetRead,
    AccountPresetUpdate,
    AttachAccountRequest,
    CampaignAccountRead,
    CampaignAccountUpdate,
    CampaignCreate,
    CampaignRead,
    CampaignUpdate,
    CommentLogRead,
    DelayPresetCreate,
    DelayPresetRead,
    DelayPresetUpdate,
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
    body: CampaignCreate,
    session: Session = Depends(get_session),
    _limit: None = Depends(enforce_limit("campaigns_active_max")),
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


@router.delete(
    "/campaigns/{campaign_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
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
            session,
            publisher,
            campaign_id,
            body.account_id,
            body.override_prompt,
            body.probability_override,
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


@router.patch(
    "/campaigns/{campaign_id}/accounts/{account_id}",
    response_model=CampaignAccountRead,
)
def patch_campaign_account(
    campaign_id: int,
    account_id: int,
    body: CampaignAccountUpdate,
    session: Session = Depends(get_session),
) -> CampaignAccountRead:
    """Патч привязки (пока — probability_override, override_prompt).

    Используется для тумблера «Пер-аккаунтная вероятность» в UI при
    ``post_selection_mode='probability'``.
    """
    link = CampaignAccountRepository(session).update(campaign_id, account_id, body)
    if link is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"account {account_id} is not attached to campaign {campaign_id}",
        )
    session.commit()
    return CampaignAccountRead.model_validate(link)


@router.delete(
    "/campaigns/{campaign_id}/accounts/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
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


# --- Пресеты аккаунтов ------------------------------------------------------


@router.get("/presets/accounts", response_model=list[AccountPresetRead])
def list_account_presets(
    session: Session = Depends(get_session),
    user_id: str = Depends(require_user),
) -> list[AccountPresetRead]:
    presets = AccountPresetRepository(session).list_by_owner(user_id)
    return [AccountPresetRead.model_validate(p) for p in presets]


@router.post(
    "/presets/accounts",
    response_model=AccountPresetRead,
    status_code=status.HTTP_201_CREATED,
)
def create_account_preset(
    body: AccountPresetCreate,
    session: Session = Depends(get_session),
    user_id: str = Depends(require_user),
) -> AccountPresetRead:
    preset = AccountPresetRepository(session).create(user_id, body)
    session.commit()
    return AccountPresetRead.model_validate(preset)


@router.patch("/presets/accounts/{preset_id}", response_model=AccountPresetRead)
def update_account_preset(
    preset_id: int,
    body: AccountPresetUpdate,
    session: Session = Depends(get_session),
    user_id: str = Depends(require_user),
) -> AccountPresetRead:
    preset = AccountPresetRepository(session).update(preset_id, user_id, body)
    if preset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "preset not found")
    session.commit()
    return AccountPresetRead.model_validate(preset)


@router.delete(
    "/presets/accounts/{preset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def delete_account_preset(
    preset_id: int,
    session: Session = Depends(get_session),
    user_id: str = Depends(require_user),
) -> None:
    if not AccountPresetRepository(session).delete(preset_id, user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "preset not found")
    session.commit()


# --- Пресеты задержек -------------------------------------------------------


@router.get("/presets/delays", response_model=list[DelayPresetRead])
def list_delay_presets(
    session: Session = Depends(get_session),
    user_id: str = Depends(require_user),
) -> list[DelayPresetRead]:
    presets = DelayPresetRepository(session).list_visible(user_id)
    return [DelayPresetRead.model_validate(p) for p in presets]


@router.post(
    "/presets/delays",
    response_model=DelayPresetRead,
    status_code=status.HTTP_201_CREATED,
)
def create_delay_preset(
    body: DelayPresetCreate,
    session: Session = Depends(get_session),
    user_id: str = Depends(require_user),
) -> DelayPresetRead:
    preset = DelayPresetRepository(session).create(user_id, body)
    session.commit()
    return DelayPresetRead.model_validate(preset)


@router.patch("/presets/delays/{preset_id}", response_model=DelayPresetRead)
def update_delay_preset(
    preset_id: int,
    body: DelayPresetUpdate,
    session: Session = Depends(get_session),
    user_id: str = Depends(require_user),
) -> DelayPresetRead:
    preset = DelayPresetRepository(session).update(preset_id, user_id, body)
    if preset is None:
        # Может быть 404 (нет) или попытка редактировать системный (не own).
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "preset not found or not editable"
        )
    session.commit()
    return DelayPresetRead.model_validate(preset)


@router.delete(
    "/presets/delays/{preset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def delete_delay_preset(
    preset_id: int,
    session: Session = Depends(get_session),
    user_id: str = Depends(require_user),
) -> None:
    if not DelayPresetRepository(session).delete(preset_id, user_id):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "preset not found or not deletable"
        )
    session.commit()


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
