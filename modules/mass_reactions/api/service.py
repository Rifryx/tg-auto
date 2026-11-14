"""Сервисный слой API масс-реакций: CRUD + жизненный цикл кампании."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from modules.mass_reactions.models import MassReactionCampaign
from modules.mass_reactions.repositories import (
    CampaignAccountRepository,
    CampaignChatRepository,
    CampaignRepository,
    LogRepository,
)
from modules.mass_reactions.schemas.enums import MassReactionCampaignStatus
from modules.mass_reactions.service import add_chats_from_list

_EDITABLE = {
    MassReactionCampaignStatus.DRAFT.value,
    MassReactionCampaignStatus.PAUSED.value,
}
_DELETABLE = {
    MassReactionCampaignStatus.DRAFT.value,
    MassReactionCampaignStatus.STOPPED.value,
    MassReactionCampaignStatus.FINISHED.value,
    MassReactionCampaignStatus.FAILED.value,
}


def _get_or_404(session: Session, campaign_id: int) -> MassReactionCampaign:
    c = CampaignRepository(session).get(campaign_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "campaign not found")
    return c


def list_campaigns(
    session: Session, owner_user_id: str
) -> list[MassReactionCampaign]:
    # Multi-tenancy: только свои кампании.
    return CampaignRepository(session).list_by_owner(owner_user_id)


def get_campaign(session: Session, campaign_id: int) -> MassReactionCampaign:
    return _get_or_404(session, campaign_id)


def create_campaign(
    session: Session, data: Mapping[str, Any], owner_user_id: str
) -> MassReactionCampaign:
    payload = dict(data)
    # Владельца проставляем из require_user (игнорируем значение из тела).
    payload["owner_user_id"] = owner_user_id
    return CampaignRepository(session).create(payload)


def update_campaign(
    session: Session, campaign_id: int, data: Mapping[str, Any]
) -> MassReactionCampaign:
    c = _get_or_404(session, campaign_id)
    if c.status not in _EDITABLE:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"campaign is '{c.status}'; editable only in {sorted(_EDITABLE)}",
        )
    payload = {k: v for k, v in data.items() if v is not None}
    if not payload:
        return c
    return CampaignRepository(session).update(campaign_id, payload)


def delete_campaign(session: Session, campaign_id: int) -> None:
    c = _get_or_404(session, campaign_id)
    if c.status not in _DELETABLE:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"campaign is '{c.status}'; deletable only in {sorted(_DELETABLE)}",
        )
    CampaignRepository(session).delete_hard(campaign_id)


def set_status(
    session: Session, campaign_id: int, new_status: str, *, allowed_from: set[str]
) -> MassReactionCampaign:
    c = _get_or_404(session, campaign_id)
    if c.status not in allowed_from:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"cannot set '{new_status}' from '{c.status}'",
        )
    extra: dict[str, Any] = {"status": new_status}
    if new_status == MassReactionCampaignStatus.RUNNING.value and c.started_at is None:
        now = datetime.now(timezone.utc)
        extra["started_at"] = now
        extra["expires_at"] = now + timedelta(hours=c.duration_hours)
    return CampaignRepository(session).update(campaign_id, extra)


def start_campaign(session: Session, campaign_id: int) -> MassReactionCampaign:
    return set_status(
        session, campaign_id,
        MassReactionCampaignStatus.RUNNING.value,
        allowed_from={
            MassReactionCampaignStatus.DRAFT.value,
            MassReactionCampaignStatus.PAUSED.value,
            MassReactionCampaignStatus.STOPPED.value,
        },
    )


def pause_campaign(session: Session, campaign_id: int) -> MassReactionCampaign:
    return set_status(
        session, campaign_id, MassReactionCampaignStatus.PAUSED.value,
        allowed_from={MassReactionCampaignStatus.RUNNING.value},
    )


def stop_campaign(session: Session, campaign_id: int) -> MassReactionCampaign:
    return set_status(
        session, campaign_id, MassReactionCampaignStatus.STOPPED.value,
        allowed_from={
            MassReactionCampaignStatus.RUNNING.value,
            MassReactionCampaignStatus.PAUSED.value,
        },
    )


def list_chats(session: Session, campaign_id: int):
    _get_or_404(session, campaign_id)
    return CampaignChatRepository(session).list_by_campaign(campaign_id)


def add_chats(session: Session, campaign_id: int, raw_text: str, notify_mode: str):
    _get_or_404(session, campaign_id)
    return add_chats_from_list(session, campaign_id, raw_text, notify_mode=notify_mode)


def list_accounts(session: Session, campaign_id: int):
    _get_or_404(session, campaign_id)
    return CampaignAccountRepository(session).list_by_campaign(campaign_id)


def add_accounts(
    session: Session, campaign_id: int, account_ids: list[int], owner_user_id: str
):
    _get_or_404(session, campaign_id)
    # Multi-tenancy: привязать можно только СВОИ аккаунты (кампания уже
    # проверена owner-guard'ом роутера). Чужой/несуществующий id → 404.
    from core.repositories.account import AccountRepository

    acc_repo = AccountRepository(session)
    for aid in account_ids:
        acc = acc_repo.get(aid)
        if acc is None or acc.user_id != owner_user_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"account {aid} not found")
    repo = CampaignAccountRepository(session)
    existing = {a.account_id for a in repo.list_by_campaign(campaign_id)}
    created = []
    for aid in account_ids:
        if aid in existing:
            continue
        existing.add(aid)
        created.append(repo.create({"campaign_id": campaign_id, "account_id": aid}))
    return created


def logs_stats(session: Session, campaign_id: int) -> dict[str, int]:
    _get_or_404(session, campaign_id)
    return LogRepository(session).count_by_outcome(campaign_id)
