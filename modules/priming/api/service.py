"""Сервисный слой API модуля прайминга (промпт 2.4).

Здесь живут переходы статусов кампании, валидация «можно ли стартовать»
и оркестрация задач arq. Роутер (``router.py``) — тонкая обёртка, только
превращает исключения сервиса в HTTP-ответы.

Инварианты:
* Правки кампании — только в ``draft`` / ``paused``.
* Удаление — только в ``draft`` / ``finished`` / ``failed``.
* ``start`` требует минимум 1 аккаунт + 1 pending-цель.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.queue import TaskQueue
from core.queue.task_names import TaskName
from modules.priming.models import PrimingCampaignAccount, PrimingCampaignTarget
from modules.priming.repositories import (
    CampaignRepository,
    CampaignAccountRepository,
    CampaignTargetRepository,
)
from modules.priming.schemas.enums import (
    PrimingCampaignStatus,
    TargetStatus,
    TriggerAction,
)


class ServiceError(Exception):
    """Базовый класс ошибок сервиса.

    Роутер маппит подклассы в конкретные HTTP-коды (см. ``router.py``).
    """

    code = "priming_error"
    status_code = 400


class NotFoundError(ServiceError):
    code = "not_found"
    status_code = 404


class ConflictError(ServiceError):
    code = "conflict"
    status_code = 409


class ValidationError(ServiceError):
    code = "validation_error"
    status_code = 422


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

_EDITABLE_STATUSES = {
    PrimingCampaignStatus.DRAFT.value,
    PrimingCampaignStatus.PAUSED.value,
}

_DELETABLE_STATUSES = {
    PrimingCampaignStatus.DRAFT.value,
    PrimingCampaignStatus.FINISHED.value,
    PrimingCampaignStatus.FAILED.value,
}


def create_campaign(session: Session, data: Mapping[str, Any]):
    """Создаёт кампанию в ``draft`` (server_default покроет status)."""
    payload = dict(data)
    # trigger_action может прийти как enum-member — приведём к value.
    if isinstance(payload.get("trigger_action"), TriggerAction):
        payload["trigger_action"] = payload["trigger_action"].value
    return CampaignRepository(session).create(payload)


def get_campaign(session: Session, campaign_id: int):
    campaign = CampaignRepository(session).get_by_id(campaign_id)
    if campaign is None:
        raise NotFoundError(f"campaign {campaign_id} not found")
    return campaign


def update_campaign(session: Session, campaign_id: int, data: Mapping[str, Any]):
    campaign = get_campaign(session, campaign_id)
    if campaign.status not in _EDITABLE_STATUSES:
        raise ConflictError(
            f"campaign {campaign_id} is '{campaign.status}'; editable only in "
            f"{sorted(_EDITABLE_STATUSES)}"
        )
    payload = {k: v for k, v in data.items() if v is not None}
    if not payload:
        return campaign
    # enum → value.
    for key, value in list(payload.items()):
        if hasattr(value, "value"):
            payload[key] = value.value
    return CampaignRepository(session).update(campaign_id, payload)


def delete_campaign(session: Session, campaign_id: int) -> None:
    campaign = get_campaign(session, campaign_id)
    if campaign.status not in _DELETABLE_STATUSES:
        raise ConflictError(
            f"campaign {campaign_id} is '{campaign.status}'; deletable only in "
            f"{sorted(_DELETABLE_STATUSES)}"
        )
    CampaignRepository(session).delete_hard(campaign_id)


# ---------------------------------------------------------------------------
# Lifecycle: start / pause / resume / stop
# ---------------------------------------------------------------------------

async def start_campaign(
    session: Session,
    campaign_id: int,
    task_queue: TaskQueue,
    *,
    now: datetime | None = None,
):
    """Валидирует и переводит в ``running``, планирует первый tick."""
    campaign = get_campaign(session, campaign_id)
    if campaign.status not in {
        PrimingCampaignStatus.DRAFT.value,
        PrimingCampaignStatus.PAUSED.value,
        PrimingCampaignStatus.STOPPED.value,
    }:
        raise ConflictError(
            f"cannot start campaign in status '{campaign.status}'"
        )

    _validate_startable(session, campaign_id)

    now = now or datetime.now(timezone.utc)
    updated = CampaignRepository(session).update(campaign_id, {
        "status": PrimingCampaignStatus.RUNNING.value,
        "started_at": now,
        "finished_at": None,
    })
    session.commit()

    await task_queue.enqueue(
        TaskName.PRIMING_ORCHESTRATOR_TICK, campaign_id,
    )
    return updated


def pause_campaign(session: Session, campaign_id: int):
    campaign = get_campaign(session, campaign_id)
    if campaign.status != PrimingCampaignStatus.RUNNING.value:
        raise ConflictError(
            f"cannot pause campaign in status '{campaign.status}'"
        )
    return CampaignRepository(session).set_status(
        campaign_id, PrimingCampaignStatus.PAUSED.value,
    )


async def resume_campaign(
    session: Session, campaign_id: int, task_queue: TaskQueue,
):
    campaign = get_campaign(session, campaign_id)
    if campaign.status != PrimingCampaignStatus.PAUSED.value:
        raise ConflictError(
            f"cannot resume campaign in status '{campaign.status}'"
        )
    updated = CampaignRepository(session).set_status(
        campaign_id, PrimingCampaignStatus.RUNNING.value,
    )
    session.commit()
    await task_queue.enqueue(
        TaskName.PRIMING_ORCHESTRATOR_TICK, campaign_id,
    )
    return updated


def stop_campaign(session: Session, campaign_id: int):
    campaign = get_campaign(session, campaign_id)
    if campaign.status not in {
        PrimingCampaignStatus.RUNNING.value,
        PrimingCampaignStatus.PAUSED.value,
    }:
        raise ConflictError(
            f"cannot stop campaign in status '{campaign.status}'"
        )
    return CampaignRepository(session).update(campaign_id, {
        "status": PrimingCampaignStatus.STOPPED.value,
        "finished_at": datetime.now(timezone.utc),
    })


# ---------------------------------------------------------------------------
# Валидация startable
# ---------------------------------------------------------------------------

def _validate_startable(session: Session, campaign_id: int) -> None:
    accounts = session.execute(
        select(func.count()).select_from(PrimingCampaignAccount).where(
            PrimingCampaignAccount.campaign_id == campaign_id,
        )
    ).scalar_one()
    if accounts == 0:
        raise ValidationError("campaign has no accounts attached")

    pending_targets = session.execute(
        select(func.count()).select_from(PrimingCampaignTarget).where(
            PrimingCampaignTarget.campaign_id == campaign_id,
            PrimingCampaignTarget.status == TargetStatus.PENDING.value,
        )
    ).scalar_one()
    if pending_targets == 0:
        raise ValidationError("campaign has no pending targets")
