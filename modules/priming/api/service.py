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
from modules.parsing.repositories import (
    ParsedListRepository,
    ParsedListTargetRepository,
)
from modules.priming.models import PrimingCampaignAccount, PrimingCampaignTarget
from modules.priming.repositories import (
    BlacklistRepository,
    CampaignRepository,
    CampaignAccountRepository,
    CampaignTargetRepository,
)
from modules.priming.schemas.enums import (
    BlacklistReason,
    PrimingAccountState,
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

# ---------------------------------------------------------------------------
# Аккаунты кампании
# ---------------------------------------------------------------------------

# Статусы кампаний, в которых аккаунт считается «занятым» для эксклюзивности:
# аккаунт может быть в разных draft-кампаниях, но одновременно активно
# работать может только в одной. Правило удобно для UX — пользователь заводит
# черновики параллельно.
_ACCOUNT_BUSY_STATUSES = {
    PrimingCampaignStatus.QUEUED.value,
    PrimingCampaignStatus.RUNNING.value,
    PrimingCampaignStatus.PAUSED.value,
}


class AccountAttachResult:
    """Отчёт по bulk-прикреплению аккаунтов."""

    def __init__(self) -> None:
        self.attached: list[int] = []  # campaign_account.id
        self.skipped_busy: list[int] = []  # account_id уже в активной кампании
        self.skipped_duplicate: list[int] = []  # уже прикреплён к этой кампании

    def to_dict(self) -> dict[str, list[int]]:
        return {
            "attached": self.attached,
            "skipped_busy": self.skipped_busy,
            "skipped_duplicate": self.skipped_duplicate,
        }


def attach_accounts(
    session: Session,
    campaign_id: int,
    account_ids: list[int],
) -> AccountAttachResult:
    """Прикрепить пул аккаунтов к кампании.

    Правило эксклюзивности: аккаунт не может участвовать в другой кампании
    прайминга со статусом queued/running/paused. Проверка — на сервисе
    (per prompt 2.5). Уже прикреплённые к этой же кампании пропускаются
    без ошибки.
    """
    if not account_ids:
        raise ValidationError("account_ids must not be empty")

    get_campaign(session, campaign_id)  # 404 если нет
    result = AccountAttachResult()
    repo = CampaignAccountRepository(session)

    # Существующие связки этой кампании — быстрый lookup.
    existing = {ca.account_id for ca in repo.list_by_campaign(campaign_id)}

    # Аккаунты уже занятые другими активными кампаниями.
    busy = _accounts_busy_elsewhere(session, campaign_id, account_ids)

    for account_id in account_ids:
        if account_id in existing:
            result.skipped_duplicate.append(account_id)
            continue
        if account_id in busy:
            result.skipped_busy.append(account_id)
            continue
        created = repo.create({
            "campaign_id": campaign_id,
            "account_id": account_id,
        })
        result.attached.append(created.id)
        existing.add(account_id)

    return result


def _accounts_busy_elsewhere(
    session: Session, campaign_id: int, account_ids: list[int]
) -> set[int]:
    from sqlalchemy import select

    from modules.priming.models import PrimingCampaign

    if not account_ids:
        return set()
    stmt = (
        select(PrimingCampaignAccount.account_id)
        .join(PrimingCampaign, PrimingCampaign.id == PrimingCampaignAccount.campaign_id)
        .where(
            PrimingCampaignAccount.account_id.in_(account_ids),
            PrimingCampaignAccount.campaign_id != campaign_id,
            PrimingCampaign.status.in_(_ACCOUNT_BUSY_STATUSES),
        )
    )
    return set(session.execute(stmt).scalars())


def detach_account(session: Session, campaign_id: int, account_id: int) -> None:
    """Убирает связку campaign↔account."""
    get_campaign(session, campaign_id)
    ca = _find_link(session, campaign_id, account_id)
    if ca is None:
        raise NotFoundError(
            f"account {account_id} is not attached to campaign {campaign_id}"
        )
    CampaignAccountRepository(session).delete_hard(ca.id)


def _find_link(session: Session, campaign_id: int, account_id: int):
    from sqlalchemy import select

    stmt = select(PrimingCampaignAccount).where(
        PrimingCampaignAccount.campaign_id == campaign_id,
        PrimingCampaignAccount.account_id == account_id,
    )
    return session.execute(stmt).scalars().first()


# ---------------------------------------------------------------------------
# Targets: import / blacklist
# ---------------------------------------------------------------------------


class TargetImportResult:
    def __init__(self) -> None:
        self.inserted: int = 0
        self.skipped_duplicate: int = 0
        self.skipped_blacklisted: int = 0
        self.skipped_invalid: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "inserted": self.inserted,
            "skipped_duplicate": self.skipped_duplicate,
            "skipped_blacklisted": self.skipped_blacklisted,
            "skipped_invalid": self.skipped_invalid,
        }


def import_targets(
    session: Session,
    campaign_id: int,
    rows: list[Mapping[str, Any]],
    *,
    owner_user_id: int | None = None,
) -> TargetImportResult:
    """Массовый импорт целей.

    Дедуп:
    * внутри батча — по first-non-null из ``(tg_user_id, username, phone)``;
    * между батчем и БД — на уровне UNIQUE(campaign_id, tg_user_id)
      через bulk_create с ON CONFLICT DO NOTHING;
    * blacklist-match — предварительная фильтрация.
    """
    get_campaign(session, campaign_id)
    result = TargetImportResult()

    if not rows:
        return result

    blacklist = BlacklistRepository(session)
    seen: set[tuple] = set()
    filtered: list[dict[str, Any]] = []

    for row in rows:
        tg_user_id = row.get("tg_user_id")
        username = _normalize_username(row.get("username"))
        phone = _normalize_phone(row.get("phone"))

        if tg_user_id is None and not username and not phone:
            result.skipped_invalid += 1
            continue

        key = (tg_user_id, username, phone)
        if key in seen:
            result.skipped_duplicate += 1
            continue
        seen.add(key)

        if blacklist.match(
            owner_user_id=owner_user_id,
            tg_user_id=tg_user_id,
            username=username,
            phone=phone,
        ) is not None:
            result.skipped_blacklisted += 1
            continue

        filtered.append({
            "tg_user_id": tg_user_id,
            "username": username,
            "phone": phone,
            "has_premium": row.get("has_premium"),
            "source_id": row.get("source_id"),
        })

    if filtered:
        inserted = CampaignTargetRepository(session).bulk_create(
            campaign_id, filtered
        )
        result.inserted = inserted
        # Разница между filtered и inserted — дубли по (campaign_id, tg_user_id)
        # с уже существующими в БД.
        result.skipped_duplicate += len(filtered) - inserted

    return result


def _normalize_username(v):
    if v is None:
        return None
    s = str(v).strip().lstrip("@")
    return s or None


def _normalize_phone(v):
    if v is None:
        return None
    s = str(v).strip().replace(" ", "").replace("-", "")
    return s or None


def import_from_parsed_list(
    session: Session,
    campaign_id: int,
    parsed_list_id: int,
    *,
    owner_user_id: int | None = None,
) -> TargetImportResult:
    """Импорт целей из готового списка модуля parsing (промпт 3.2b).

    Дедуп идёт через ``CampaignTargetRepository.bulk_create``
    (ON CONFLICT DO NOTHING по (campaign_id, tg_user_id)). Blacklist
    проверяется owner + global.
    """
    get_campaign(session, campaign_id)
    parsed_list = ParsedListRepository(session).get_by_id(parsed_list_id)
    if parsed_list is None:
        raise NotFoundError(f"parsed list {parsed_list_id} not found")

    parsed_targets = ParsedListTargetRepository(session).list_by_list(
        parsed_list_id
    )
    rows = [
        {
            "tg_user_id": t.tg_user_id,
            "username": t.username,
            "phone": t.phone,
            "has_premium": t.has_premium,
            "last_seen_bucket": t.last_seen_bucket,
        }
        for t in parsed_targets
    ]
    return import_targets(
        session, campaign_id, rows, owner_user_id=owner_user_id,
    )


def bulk_blacklist_targets(
    session: Session,
    campaign_id: int,
    target_ids: list[int],
) -> int:
    """Массово помечает цели ``blacklisted`` и добавляет в кампанийный
    blacklist (с причиной ``manual``). Возвращает число затронутых целей.
    """
    if not target_ids:
        raise ValidationError("target_ids must not be empty")

    from sqlalchemy import select

    campaign = get_campaign(session, campaign_id)
    stmt = select(PrimingCampaignTarget).where(
        PrimingCampaignTarget.campaign_id == campaign_id,
        PrimingCampaignTarget.id.in_(target_ids),
    )
    targets = list(session.execute(stmt).scalars())

    blacklist = BlacklistRepository(session)
    t_repo = CampaignTargetRepository(session)

    updated = 0
    for target in targets:
        # Пишем в blacklist только уникальные идентификаторы.
        blacklist.create({
            "owner_user_id": campaign.created_by,
            "tg_user_id": target.tg_user_id,
            "username": target.username,
            "phone": target.phone,
            "reason": BlacklistReason.MANUAL.value,
        })
        # Прямая установка статуса (минуем правила переходов — оператор
        # вручную блэклистит, состояние не важно).
        target.status = TargetStatus.BLACKLISTED.value
        updated += 1
    session.flush()
    return updated


# ---------------------------------------------------------------------------
# CSV parser
# ---------------------------------------------------------------------------


def parse_csv_targets(content: bytes) -> list[dict[str, Any]]:
    """Разбирает CSV (UTF-8) с колонками ``tg_user_id / username / phone``
    (любые из них могут быть пустыми).

    Возвращает список dict'ов; служебных валидаций тут нет — их делает
    :func:`import_targets`.
    """
    import csv
    import io

    text = content.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, Any]] = []
    for record in reader:
        rows.append({
            "tg_user_id": _maybe_int(record.get("tg_user_id")),
            "username": (record.get("username") or None),
            "phone": (record.get("phone") or None),
        })
    return rows


def _maybe_int(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


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
