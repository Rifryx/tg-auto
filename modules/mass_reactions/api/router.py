"""FastAPI-роутер модуля масс-реакций."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.queue import get_task_queue
from core.queue import TaskQueue
from core.queue.task_names import TaskName
from modules.mass_reactions.api import service
from modules.mass_reactions.schemas.campaign import (
    AddAccountsBody,
    AddChatsBody,
    MassReactionAccountRead,
    MassReactionCampaignCreate,
    MassReactionCampaignRead,
    MassReactionCampaignUpdate,
    MassReactionChatRead,
)

router = APIRouter(
    prefix="/modules/mass-reactions",
    tags=["mass-reactions"],
    dependencies=[Depends(require_user)],
)


@router.get("/campaigns", response_model=list[MassReactionCampaignRead])
def list_campaigns(session: Session = Depends(get_session)):
    return service.list_campaigns(session)


@router.post(
    "/campaigns",
    response_model=MassReactionCampaignRead,
    status_code=status.HTTP_201_CREATED,
)
def create_campaign(
    body: MassReactionCampaignCreate, session: Session = Depends(get_session)
):
    return service.create_campaign(session, body.model_dump())


@router.get("/campaigns/{campaign_id}", response_model=MassReactionCampaignRead)
def get_campaign(campaign_id: int, session: Session = Depends(get_session)):
    return service.get_campaign(session, campaign_id)


@router.patch("/campaigns/{campaign_id}", response_model=MassReactionCampaignRead)
def update_campaign(
    campaign_id: int,
    body: MassReactionCampaignUpdate,
    session: Session = Depends(get_session),
):
    return service.update_campaign(session, campaign_id, body.model_dump())


@router.delete(
    "/campaigns/{campaign_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def delete_campaign(campaign_id: int, session: Session = Depends(get_session)):
    service.delete_campaign(session, campaign_id)


@router.post("/campaigns/{campaign_id}/start", response_model=MassReactionCampaignRead)
async def start_campaign(
    campaign_id: int,
    session: Session = Depends(get_session),
    queue: TaskQueue = Depends(get_task_queue),
):
    campaign = service.start_campaign(session, campaign_id)
    # Запускаем раскладчик: он назначит чаты аккаунтам и запланирует себя дальше.
    await queue.enqueue(TaskName.MASS_REACTIONS_ORCHESTRATOR_TICK, campaign_id)
    return campaign


@router.post("/campaigns/{campaign_id}/pause", response_model=MassReactionCampaignRead)
def pause_campaign(campaign_id: int, session: Session = Depends(get_session)):
    return service.pause_campaign(session, campaign_id)


@router.post("/campaigns/{campaign_id}/stop", response_model=MassReactionCampaignRead)
def stop_campaign(campaign_id: int, session: Session = Depends(get_session)):
    return service.stop_campaign(session, campaign_id)


@router.get(
    "/campaigns/{campaign_id}/chats", response_model=list[MassReactionChatRead]
)
def list_chats(campaign_id: int, session: Session = Depends(get_session)):
    return service.list_chats(session, campaign_id)


@router.post(
    "/campaigns/{campaign_id}/chats",
    response_model=list[MassReactionChatRead],
    status_code=status.HTTP_201_CREATED,
)
def add_chats(
    campaign_id: int, body: AddChatsBody, session: Session = Depends(get_session)
):
    return service.add_chats(session, campaign_id, body.raw_text, body.notify_mode)


@router.get(
    "/campaigns/{campaign_id}/accounts", response_model=list[MassReactionAccountRead]
)
def list_accounts(campaign_id: int, session: Session = Depends(get_session)):
    return service.list_accounts(session, campaign_id)


@router.post(
    "/campaigns/{campaign_id}/accounts",
    response_model=list[MassReactionAccountRead],
    status_code=status.HTTP_201_CREATED,
)
def add_accounts(
    campaign_id: int, body: AddAccountsBody, session: Session = Depends(get_session)
):
    return service.add_accounts(session, campaign_id, body.account_ids)


@router.get("/campaigns/{campaign_id}/logs/stats")
def logs_stats(campaign_id: int, session: Session = Depends(get_session)):
    return service.logs_stats(session, campaign_id)
