"""Роутер модуля прайминга (промпт 2.4).

Префикс ``/modules/priming``. На этом промпте — CRUD кампаний и
lifecycle-переходы (start / pause / resume / stop). Аккаунты/цели/
парсер/пейволл — на промптах 2.5 и далее.
"""

from __future__ import annotations

from typing import Optional

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.queue import get_task_queue
from core.queue import TaskQueue
from modules.priming.api import service
from modules.priming.repositories import (
    CampaignAccountRepository,
    CampaignRepository,
    CampaignTargetRepository,
)
from modules.priming.schemas import (
    PrimingCampaignCreate,
    PrimingCampaignRead,
    PrimingCampaignStatus,
    PrimingCampaignUpdate,
    PrimingTargetBulkBlacklist,
    PrimingTargetImport,
    PrimingTargetRead,
    TargetStatus,
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


# ---------------------------------------------------------------------------
# Аккаунты кампании
# ---------------------------------------------------------------------------


class AttachAccountsBody(dict):
    """Обёртка позволяет использовать простую JSON-схему без Pydantic-класса."""


@router.get("/campaigns/{campaign_id}/accounts")
def list_campaign_accounts(
    campaign_id: int, session: Session = Depends(get_session),
):
    try:
        service.get_campaign(session, campaign_id)
    except service.ServiceError as exc:
        _raise(exc)
    return [
        {
            "id": ca.id,
            "campaign_id": ca.campaign_id,
            "account_id": ca.account_id,
            "state": ca.state,
            "flood_waits_consecutive": ca.flood_waits_consecutive,
            "flood_waits_total": ca.flood_waits_total,
            "primes_today": ca.primes_today,
            "primes_total": ca.primes_total,
            "last_prime_at": ca.last_prime_at,
            "next_available_at": ca.next_available_at,
        }
        for ca in CampaignAccountRepository(session).list_by_campaign(campaign_id)
    ]


@router.post("/campaigns/{campaign_id}/accounts")
def attach_accounts(
    campaign_id: int,
    body: dict = Body(...),
    session: Session = Depends(get_session),
):
    account_ids = body.get("account_ids") or []
    if not isinstance(account_ids, list) or not all(
        isinstance(x, int) for x in account_ids
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "validation_error",
                "message": "account_ids must be a non-empty list[int]",
            },
        )
    try:
        result = service.attach_accounts(session, campaign_id, account_ids)
    except service.ServiceError as exc:
        _raise(exc)
    session.commit()
    return result.to_dict()


@router.delete(
    "/campaigns/{campaign_id}/accounts/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def detach_account(
    campaign_id: int,
    account_id: int,
    session: Session = Depends(get_session),
):
    try:
        service.detach_account(session, campaign_id, account_id)
    except service.ServiceError as exc:
        _raise(exc)
    session.commit()
    return None


# ---------------------------------------------------------------------------
# Targets: list / import / blacklist
# ---------------------------------------------------------------------------


@router.get("/campaigns/{campaign_id}/targets", response_model=list[PrimingTargetRead])
def list_targets(
    campaign_id: int,
    session: Session = Depends(get_session),
    status: Optional[TargetStatus] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    try:
        service.get_campaign(session, campaign_id)
    except service.ServiceError as exc:
        _raise(exc)
    rows = CampaignTargetRepository(session).list_by_campaign(
        campaign_id,
        status=status.value if status else None,
        limit=limit,
        offset=offset,
    )
    return [PrimingTargetRead.model_validate(t) for t in rows]


@router.post("/campaigns/{campaign_id}/targets/import")
async def import_targets(
    campaign_id: int,
    request: Request,
    session: Session = Depends(get_session),
    file: Optional[UploadFile] = File(default=None),
):
    """Импорт целей: multipart/form-data с ``file`` (CSV) ИЛИ JSON с
    ``PrimingTargetImport``."""
    if file is not None:
        content = await file.read()
        rows = service.parse_csv_targets(content)
    else:
        body = await request.json()
        try:
            payload = PrimingTargetImport.model_validate(body)
        except Exception as exc:
            raise HTTPException(status_code=422, detail={
                "error": "validation_error", "message": str(exc),
            })
        rows = [t.model_dump() for t in payload.targets]

    try:
        campaign = service.get_campaign(session, campaign_id)
        result = service.import_targets(
            session, campaign_id, rows, owner_user_id=campaign.created_by,
        )
    except service.ServiceError as exc:
        _raise(exc)
    session.commit()
    return result.to_dict()


@router.post("/campaigns/{campaign_id}/targets/import-list")
def import_from_list(
    campaign_id: int,
    body: dict = Body(...),
    session: Session = Depends(get_session),
):
    parsed_list_id = body.get("parsed_list_id")
    if not isinstance(parsed_list_id, int):
        raise HTTPException(status_code=422, detail={
            "error": "validation_error",
            "message": "parsed_list_id must be int",
        })
    try:
        campaign = service.get_campaign(session, campaign_id)
        result = service.import_from_parsed_list(
            session, campaign_id, parsed_list_id,
            owner_user_id=campaign.created_by,
        )
    except service.ServiceError as exc:
        _raise(exc)
    session.commit()
    return result.to_dict()


@router.post("/campaigns/{campaign_id}/targets/blacklist")
def blacklist_targets(
    campaign_id: int,
    body: PrimingTargetBulkBlacklist,
    session: Session = Depends(get_session),
):
    try:
        updated = service.bulk_blacklist_targets(
            session, campaign_id, body.target_ids,
        )
    except service.ServiceError as exc:
        _raise(exc)
    session.commit()
    return {"blacklisted": updated}
