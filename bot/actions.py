"""Действия чат-бота над доменом — с проверкой владения (ownership).

Этот слой не знает про aiogram: чистые функции над БД и очередью задач,
чтобы их можно было тестировать и переиспользовать и из команд, и из
inline-кнопок. Правило владения одно на всё:

* Прайминг-кампания: ``created_by == requester_id`` ИЛИ requester — админ.
* Аккаунт: ``owner_user_id == requester_id`` ИЛИ requester — админ.
  ``owner_user_id IS NULL`` (общий/legacy-пул) — только админ.

Нарушение владения выглядит как «не найдено» (:class:`NotOwned`), чтобы
не подтверждать существование чужих объектов.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.config import get_settings
from core.enums import Initiator
from core.models import Account
from core.queue import TaskQueue
from core.queue.publisher import build_redis_publisher
from core.state_machine import AccountEvent, AccountStateMachine, TransitionError
from modules.priming.api import service as priming_service
from modules.priming.models import PrimingCampaign, PrimingCampaignAccount
from modules.priming.repositories import (
    CampaignRepository,
    CampaignTargetRepository,
)
from modules.priming.schemas.enums import PrimingCampaignStatus


# --- ошибки (единый стиль, роутер команд маппит в текст) ----------------------


class ActionError(Exception):
    """Базовая ошибка действия; .user_msg — что показать пользователю."""

    def __init__(self, user_msg: str) -> None:
        super().__init__(user_msg)
        self.user_msg = user_msg


class NotOwned(ActionError):
    """Объект не принадлежит пользователю (или не существует)."""

    def __init__(self, what: str = "Объект") -> None:
        super().__init__(f"{what} не найден или недоступен.")


class Conflict(ActionError):
    """Действие невозможно в текущем статусе."""


# --- helpers ------------------------------------------------------------------


def is_admin(user_id: int) -> bool:
    return str(user_id) in get_settings().admin_ids


def _publisher():
    """Sync-publisher для state machine (пишет в тот же Redis pub/sub)."""
    try:
        return build_redis_publisher(get_settings().redis_url)
    except Exception:  # noqa: BLE001 — без Redis действие всё равно выполним
        return None


# --- ПРАЙМИНГ: список и владение ----------------------------------------------


def list_owned_campaigns(
    session: Session, requester_id: int, *, limit: int = 20
) -> list[PrimingCampaign]:
    """Кампании пользователя (или все — если админ), новые сверху."""
    stmt = select(PrimingCampaign).order_by(
        PrimingCampaign.created_at.desc(), PrimingCampaign.id.desc()
    )
    if not is_admin(requester_id):
        stmt = stmt.where(PrimingCampaign.created_by == requester_id)
    stmt = stmt.limit(limit)
    return list(session.execute(stmt).scalars())


def get_owned_campaign(
    session: Session, campaign_id: int, requester_id: int
) -> PrimingCampaign:
    camp = CampaignRepository(session).get_by_id(campaign_id)
    if camp is None:
        raise NotOwned("Кампания")
    if camp.created_by != requester_id and not is_admin(requester_id):
        raise NotOwned("Кампания")
    return camp


def campaign_counts(session: Session, campaign_id: int) -> dict:
    """Короткая сводка кампании: аккаунты и цели по ключевым состояниям."""
    acc_rows = session.execute(
        select(PrimingCampaignAccount.state, func.count())
        .where(PrimingCampaignAccount.campaign_id == campaign_id)
        .group_by(PrimingCampaignAccount.state)
    ).all()
    accounts = {r[0]: int(r[1]) for r in acc_rows}
    targets = CampaignTargetRepository(session).count_by_status(campaign_id)
    return {"accounts": accounts, "targets": targets}


# --- ПРАЙМИНГ: действия -------------------------------------------------------


def do_pause(session: Session, campaign_id: int, requester_id: int) -> PrimingCampaign:
    get_owned_campaign(session, campaign_id, requester_id)
    try:
        camp = priming_service.pause_campaign(session, campaign_id)
    except priming_service.ConflictError as exc:
        raise Conflict(f"Нельзя поставить на паузу: {exc}") from exc
    session.commit()
    return camp


async def do_resume(
    session: Session, campaign_id: int, requester_id: int, task_queue: TaskQueue
) -> PrimingCampaign:
    get_owned_campaign(session, campaign_id, requester_id)
    try:
        camp = await priming_service.resume_campaign(session, campaign_id, task_queue)
    except priming_service.ConflictError as exc:
        raise Conflict(f"Нельзя возобновить: {exc}") from exc
    return camp


def do_stop(session: Session, campaign_id: int, requester_id: int) -> PrimingCampaign:
    get_owned_campaign(session, campaign_id, requester_id)
    try:
        camp = priming_service.stop_campaign(session, campaign_id)
    except priming_service.ConflictError as exc:
        raise Conflict(f"Нельзя остановить: {exc}") from exc
    session.commit()
    return camp


async def do_repeat(
    session: Session,
    requester_id: int,
    task_queue: TaskQueue,
    *,
    campaign_id: Optional[int] = None,
) -> tuple[PrimingCampaign, bool]:
    """Дублирует кампанию и пытается сразу запустить.

    Возвращает (новая_кампания, запущена?). Если валидатор не пропустил
    (нет аккаунтов/целей) — остаётся draft, второй элемент False.
    """
    if campaign_id is not None:
        source = get_owned_campaign(session, campaign_id, requester_id)
    else:
        source = _latest_repeatable(session, requester_id)
        if source is None:
            raise NotOwned("Завершённая кампания для повтора")

    clone = priming_service.duplicate_campaign(session, source.id)
    session.commit()
    try:
        await priming_service.start_campaign(session, clone.id, task_queue)
        return clone, True
    except priming_service.ServiceError:
        # Дубликат остаётся черновиком — пользователь доведёт в Mini App.
        return clone, False


def _latest_repeatable(
    session: Session, requester_id: int
) -> Optional[PrimingCampaign]:
    repeatable = (
        PrimingCampaignStatus.FINISHED.value,
        PrimingCampaignStatus.STOPPED.value,
        PrimingCampaignStatus.PAUSED.value,
    )
    stmt = (
        select(PrimingCampaign)
        .where(PrimingCampaign.status.in_(repeatable))
        .order_by(PrimingCampaign.created_at.desc(), PrimingCampaign.id.desc())
        .limit(1)
    )
    if not is_admin(requester_id):
        stmt = stmt.where(PrimingCampaign.created_by == requester_id)
    return session.execute(stmt).scalars().first()


# --- АККАУНТЫ: владение + карантин --------------------------------------------


def get_owned_account(
    session: Session, account_id: int, requester_id: int
) -> Account:
    acc = session.get(Account, account_id)
    if acc is None:
        raise NotOwned("Аккаунт")
    owner = acc.owner_user_id
    if owner == requester_id:
        return acc
    # NULL-owner (общий пул) и чужие — только админу.
    if is_admin(requester_id):
        return acc
    raise NotOwned("Аккаунт")


def quarantine_account(
    session: Session, account_id: int, requester_id: int
) -> Account:
    """Вывести аккаунт из работы (RETIRE). Обратимо через unquarantine."""
    acc = get_owned_account(session, account_id, requester_id)
    try:
        updated = AccountStateMachine(session, _publisher()).transition(
            account_id, AccountEvent.RETIRE, Initiator.USER,
        )
    except TransitionError as exc:
        raise Conflict(
            f"Нельзя вывести аккаунт из статуса «{acc.status}»."
        ) from exc
    return updated


def unquarantine_account(
    session: Session, account_id: int, requester_id: int
) -> Account:
    """Вернуть выведенный аккаунт в пул (RESTORE)."""
    acc = get_owned_account(session, account_id, requester_id)
    try:
        updated = AccountStateMachine(session, _publisher()).transition(
            account_id, AccountEvent.RESTORE, Initiator.USER,
        )
    except TransitionError as exc:
        raise Conflict(
            f"Нельзя вернуть аккаунт из статуса «{acc.status}» "
            f"(возврат только из «retired»)."
        ) from exc
    return updated
