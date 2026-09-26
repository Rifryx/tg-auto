"""Бизнес-логика модуля НейроШиллинг: исключения + транзакционные операции.

Роутер ловит эти исключения и мапит их на HTTP-коды.
"""

from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from core.enums import AccountStatus
from core.repositories.account import AccountRepository
from modules.shilling.models import (
    ShillingCampaignAccount,
    ShillingScenario,
    ShillingScenarioStep,
    ShillingTarget,
)
from modules.shilling.repositories import (
    CampaignAccountRepository,
    CampaignRepository,
    CampaignTargetRepository,
    ExecutionLogRepository,
    ScenarioRepository,
    ScenarioRoleRepository,
    ScenarioStepRepository,
)
from modules.shilling.schemas import (
    CampaignReadiness,
    CampaignStats,
    ReadinessCheck,
)

# Аккаунт годен для шиллинга, если он прогрет и операционен. Шиллинг
# non-exclusive (аккаунт может быть в нескольких кампаниях), поэтому статус
# аккаунта НЕ меняется через state machine — только записывается связка.
_USABLE_ACCOUNT_STATUSES = {AccountStatus.POOL.value, AccountStatus.ASSIGNED.value}


class ShillingNotFound(Exception):
    """Сущность (кампания/сценарий/роль/шаг/цель) не найдена → 404."""


class ShillingConflict(Exception):
    """Недопустимое состояние для операции → 409."""


class ShillingValidation(Exception):
    """Данные не проходят бизнес-валидацию (не путать с pydantic 422) → 400."""


# ---------------------------------------------------------------------------
# Сценарии
# ---------------------------------------------------------------------------


def upsert_scenario_for_campaign(
    session: Session,
    campaign_id: int,
    data,
) -> ShillingScenario:
    """PUT /campaigns/{id}/scenario — создать или заменить сценарий кампании.

    Реализация: если у кампании уже есть сценарий, ЗАМЕНЯЕМ его новым
    (старый удаляется каскадом вместе с ролями/шагами — scenario_id в
    таблицах ролей/шагов идёт с ondelete=CASCADE через FK на scenarios.id).
    Флаг ``ai_generated`` и ``persons_count`` из тела применяются.
    """
    campaign = CampaignRepository(session).get(campaign_id)
    if campaign is None:
        raise ShillingNotFound(f"campaign {campaign_id} not found")

    existing = ScenarioRepository(session).get_by_campaign(campaign_id)
    if existing is not None:
        # Разрываем ссылку с campaigns.scenario_id перед удалением, чтобы
        # SET NULL при DROP сценария не оставил зависший id в campaigns.
        if campaign.scenario_id == existing.id:
            campaign.scenario_id = None
            session.flush()
        session.delete(existing)
        session.flush()

    payload = data.model_dump(exclude_unset=True)
    payload["campaign_id"] = campaign_id
    scenario = ShillingScenario(**payload)
    session.add(scenario)
    session.flush()
    campaign.scenario_id = scenario.id
    session.flush()
    return scenario


# ---------------------------------------------------------------------------
# Роли
# ---------------------------------------------------------------------------


def delete_role(session: Session, scenario_id: int, role_id: int) -> None:
    """DELETE роли: 404 если нет, 409 если на неё ссылаются шаги.

    Не пытаемся auto-null'ить — роль обязательна для шага. Оператор должен
    сначала переназначить/удалить эти шаги.
    """
    role_repo = ScenarioRoleRepository(session)
    role = role_repo.get(role_id)
    if role is None or role.scenario_id != scenario_id:
        raise ShillingNotFound(f"role {role_id} not found in scenario {scenario_id}")

    step_repo = ScenarioStepRepository(session)
    dependents = step_repo.list_by_role(role_id)
    if dependents:
        raise ShillingConflict(
            f"cannot delete role: {len(dependents)} step(s) still reference it; "
            "remove or reassign those steps first"
        )

    session.delete(role)
    session.flush()


# ---------------------------------------------------------------------------
# Шаги
# ---------------------------------------------------------------------------


def delete_step(session: Session, scenario_id: int, step_id: int) -> int:
    """DELETE шага + автообнуление reply_to_step_id у ссылающихся.

    Возвращает число шагов, у которых reply_to пришлось обнулить. БД делает
    это через FK ondelete=SET NULL, но здесь мы делаем это ЯВНО одной
    транзакционной UPDATE — так у сервис-слоя есть точный счёт (для
    логов/ответа) и порядок операций предсказуем.
    """
    step_repo = ScenarioStepRepository(session)
    step = step_repo.get(step_id)
    if step is None or step.scenario_id != scenario_id:
        raise ShillingNotFound(f"step {step_id} not found in scenario {scenario_id}")

    stmt = (
        update(ShillingScenarioStep)
        .where(ShillingScenarioStep.reply_to_step_id == step_id)
        .values(reply_to_step_id=None)
    )
    affected = session.execute(stmt).rowcount or 0

    session.delete(step)
    session.flush()
    return affected


def reorder_steps(
    session: Session, scenario_id: int, step_ids_in_order: list[int]
) -> None:
    """Атомарный reorder: должен приходить ПОЛНЫЙ и уникальный список шагов.

    Требуем полный список, чтобы избежать коллизий step_order с не-переданными
    шагами (репозиторий перенумеровывает переданные с 1). Атомарность —
    в репозитории: чужой id → False, ничего не меняется.
    """
    if ScenarioRepository(session).get(scenario_id) is None:
        raise ShillingNotFound(f"scenario {scenario_id} not found")

    if len(set(step_ids_in_order)) != len(step_ids_in_order):
        raise ShillingValidation("step_ids contain duplicates")

    existing = ScenarioStepRepository(session).list_by_scenario(scenario_id)
    if len(step_ids_in_order) != len(existing):
        raise ShillingValidation(
            f"reorder expects the full list of steps "
            f"({len(existing)} in scenario, got {len(step_ids_in_order)})"
        )

    ok = ScenarioStepRepository(session).reorder(scenario_id, step_ids_in_order)
    if not ok:
        raise ShillingValidation(
            "one or more step_ids do not belong to this scenario"
        )


# ---------------------------------------------------------------------------
# Аккаунты кампании
# ---------------------------------------------------------------------------


def attach_account(
    session: Session,
    campaign_id: int,
    account_id: int,
    *,
    role_id: Optional[int] = None,
    is_reserve: bool = False,
) -> ShillingCampaignAccount:
    """Привязать аккаунт к кампании. Non-exclusive: статус аккаунта не меняем.

    Валидация:
    * кампания существует;
    * аккаунт существует и в рабочем статусе (pool/assigned);
    * роль (если задана) принадлежит сценарию этой кампании;
    * аккаунт ещё не привязан к этой кампании (UNIQUE подстрахует, но даём
      понятный 409 заранее).
    """
    campaign = CampaignRepository(session).get(campaign_id)
    if campaign is None:
        raise ShillingNotFound(f"campaign {campaign_id} not found")

    account = AccountRepository(session).get(account_id)
    if account is None:
        raise ShillingNotFound(f"account {account_id} not found")
    if account.status not in _USABLE_ACCOUNT_STATUSES:
        raise ShillingValidation(
            f"account {account_id} is '{account.status}', must be "
            f"'pool' or 'assigned' to join a shilling campaign"
        )

    if role_id is not None:
        _validate_role_in_campaign(session, campaign, role_id)

    link_repo = CampaignAccountRepository(session)
    if link_repo.get_link(campaign_id, account_id) is not None:
        raise ShillingConflict(
            f"account {account_id} is already attached to campaign {campaign_id}"
        )

    return link_repo.attach(
        campaign_id, account_id, role_id=role_id, is_reserve=is_reserve
    )


def update_account_link(
    session: Session,
    campaign_id: int,
    account_id: int,
    data,
) -> ShillingCampaignAccount:
    """PATCH привязки: смена роли / флага резерва."""
    campaign = CampaignRepository(session).get(campaign_id)
    if campaign is None:
        raise ShillingNotFound(f"campaign {campaign_id} not found")

    link_repo = CampaignAccountRepository(session)
    link = link_repo.get_link(campaign_id, account_id)
    if link is None:
        raise ShillingNotFound(
            f"account {account_id} is not attached to campaign {campaign_id}"
        )

    payload = data.model_dump(exclude_unset=True)
    if "role_id" in payload and payload["role_id"] is not None:
        _validate_role_in_campaign(session, campaign, payload["role_id"])

    updated = link_repo.update(campaign_id, account_id, data)
    return updated


def detach_account(session: Session, campaign_id: int, account_id: int) -> None:
    if CampaignRepository(session).get(campaign_id) is None:
        raise ShillingNotFound(f"campaign {campaign_id} not found")
    if not CampaignAccountRepository(session).detach(campaign_id, account_id):
        raise ShillingNotFound(
            f"account {account_id} is not attached to campaign {campaign_id}"
        )


def _validate_role_in_campaign(session: Session, campaign, role_id: int) -> None:
    """Роль должна принадлежать сценарию этой кампании (иначе 400)."""
    role = ScenarioRoleRepository(session).get(role_id)
    if role is None:
        raise ShillingValidation(f"role {role_id} not found")
    if campaign.scenario_id is None or role.scenario_id != campaign.scenario_id:
        raise ShillingValidation(
            f"role {role_id} does not belong to campaign {campaign.id}'s scenario"
        )


# ---------------------------------------------------------------------------
# Целевые каналы
# ---------------------------------------------------------------------------

_INVITE_RE = re.compile(r"(?:t\.me/|telegram\.me/)(?:joinchat/|\+)", re.IGNORECASE)
_TME_RE = re.compile(r"(?:https?://)?t\.me/", re.IGNORECASE)


def normalize_target(raw: str) -> tuple[str, str]:
    """Нормализует ввод цели → (canonical_raw_input, kind).

    * ``-1001234`` / ``1001234`` → chat_id
    * ссылка-приглашение (t.me/joinchat/…, t.me/+…) → invite (как есть, trim)
    * @username / t.me/username / username → username (без @, lower)
    """
    s = raw.strip()
    if not s:
        return s, "username"

    # chat_id: только цифры (возможно с ведущим -)
    if re.fullmatch(r"-?\d+", s):
        return s, "chat_id"

    # invite-ссылка
    if _INVITE_RE.search(s):
        return s, "invite"

    # username в любом виде → нормализуем к голому lower-case юзернейму
    s = _TME_RE.sub("", s)
    s = s.lstrip("@")
    s = s.split("/")[0].split("?")[0]  # обрезаем хвосты /42 ?comment=
    return s.lower(), "username"


def add_targets_bulk(
    session: Session, campaign_id: int, raw_inputs: list[str]
) -> list[ShillingTarget]:
    """Bulk-добавление целей. Дубли (по нормализованному raw_input) — молча."""
    if CampaignRepository(session).get(campaign_id) is None:
        raise ShillingNotFound(f"campaign {campaign_id} not found")

    from modules.shilling.schemas import TargetCreate

    repo = CampaignTargetRepository(session)
    existing = {t.raw_input for t in repo.list_by_campaign(campaign_id)}
    created: list[ShillingTarget] = []
    for raw in raw_inputs:
        canonical, kind = normalize_target(raw)
        if not canonical or canonical in existing:
            continue
        target = repo.create(
            campaign_id, TargetCreate(raw_input=canonical, kind=kind)
        )
        existing.add(canonical)
        created.append(target)
    return created


# ---------------------------------------------------------------------------
# Готовность / статистика / жизненный цикл
# ---------------------------------------------------------------------------


def compute_readiness(session: Session, campaign_id: int) -> CampaignReadiness:
    """Чеклист готовности: аккаунты, сценарий, цели. can_run = все три ok.

    * accounts: основных (не резерв) аккаунтов >= persons_count сценария.
    * scenario: есть сценарий, ≥1 роль и ≥1 шаг-сообщение; каждая роль
      покрыта хотя бы одним шагом.
    * targets: ≥1 цель.
    """
    campaign = CampaignRepository(session).get(campaign_id)
    if campaign is None:
        raise ShillingNotFound(f"campaign {campaign_id} not found")

    scenario = ScenarioRepository(session).get_by_campaign(campaign_id)
    role_repo = ScenarioRoleRepository(session)
    step_repo = ScenarioStepRepository(session)

    # --- сценарий ---
    if scenario is None:
        scenario_check = ReadinessCheck(
            ok=False, label="Сценарий не создан", reason="no_scenario"
        )
        persons_needed = 2
    else:
        roles = role_repo.list_by_scenario(scenario.id)
        steps = step_repo.list_by_scenario(scenario.id)
        message_steps = [s for s in steps if s.step_type == "message"]
        roles_with_steps = {s.role_id for s in steps}
        uncovered = [r for r in roles if r.id not in roles_with_steps]
        persons_needed = scenario.persons_count
        if not roles:
            scenario_check = ReadinessCheck(
                ok=False, label="Нет ролей в сценарии", reason="no_roles"
            )
        elif not message_steps:
            scenario_check = ReadinessCheck(
                ok=False, label="Нет реплик в сценарии", reason="no_message_steps"
            )
        elif uncovered:
            names = ", ".join(r.name for r in uncovered)
            scenario_check = ReadinessCheck(
                ok=False,
                label=f"Роли без реплик: {names}",
                reason="roles_without_steps",
            )
        else:
            scenario_check = ReadinessCheck(
                ok=True,
                label=f"Сценарий готов ({len(roles)} ролей, {len(message_steps)} реплик)",
            )

    # --- аккаунты ---
    links = CampaignAccountRepository(session).list_by_campaign(campaign_id)
    primary = [link for link in links if not link.is_reserve]
    accounts_ok = len(primary) >= persons_needed
    accounts_check = ReadinessCheck(
        ok=accounts_ok,
        label=f"Аккаунты {len(primary)}/{persons_needed}",
        reason=None if accounts_ok else "not_enough_accounts",
    )

    # --- цели ---
    targets = CampaignTargetRepository(session).list_by_campaign(campaign_id)
    targets_ok = len(targets) >= 1
    targets_check = ReadinessCheck(
        ok=targets_ok,
        label=f"Цели: {len(targets)}",
        reason=None if targets_ok else "no_targets",
    )

    return CampaignReadiness(
        accounts=accounts_check,
        scenario=scenario_check,
        targets=targets_check,
        can_run=accounts_check.ok and scenario_check.ok and targets_check.ok,
    )


def compute_stats(session: Session, campaign_id: int) -> CampaignStats:
    if CampaignRepository(session).get(campaign_id) is None:
        raise ShillingNotFound(f"campaign {campaign_id} not found")
    counts = ExecutionLogRepository(session).count_by_status(campaign_id)
    total = sum(counts.values())
    sent = counts.get("sent", 0)
    rate = (sent * 100) // total if total > 0 else 0
    return CampaignStats(
        total=total,
        sent=sent,
        failed=counts.get("failed", 0),
        skipped=counts.get("skipped", 0),
        replaced=counts.get("replaced", 0),
        success_rate_percent=rate,
    )


def prepare_start(session: Session, campaign_id: int) -> None:
    """Валидация перед стартом + перевод в running. Публикация задачи — в роуте.

    409, если кампания уже running. 400, если не готова (readiness.can_run=False).
    Коммит делает роут (после enqueue).
    """
    campaign = CampaignRepository(session).get(campaign_id)
    if campaign is None:
        raise ShillingNotFound(f"campaign {campaign_id} not found")
    if campaign.status == "running":
        raise ShillingConflict(f"campaign {campaign_id} is already running")

    readiness = compute_readiness(session, campaign_id)
    if not readiness.can_run:
        blockers = [
            c.reason
            for c in (readiness.accounts, readiness.scenario, readiness.targets)
            if not c.ok
        ]
        raise ShillingValidation(f"campaign not ready to start: {', '.join(blockers)}")

    CampaignRepository(session).set_status(campaign_id, "running")


def prepare_stop(session: Session, campaign_id: int) -> None:
    """Перевод в paused. Идемпотентно для не-running (draft/paused/completed)."""
    campaign = CampaignRepository(session).get(campaign_id)
    if campaign is None:
        raise ShillingNotFound(f"campaign {campaign_id} not found")
    CampaignRepository(session).set_status(campaign_id, "paused")
