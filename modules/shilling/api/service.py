"""Бизнес-логика модуля НейроШиллинг: исключения + транзакционные операции.

Роутер ловит эти исключения и мапит их на HTTP-коды.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from modules.shilling.models import ShillingScenarioStep
from modules.shilling.repositories import (
    CampaignRepository,
    ScenarioRepository,
    ScenarioRoleRepository,
    ScenarioStepRepository,
)


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
) -> "modules.shilling.models.ShillingScenario":
    """PUT /campaigns/{id}/scenario — создать или заменить сценарий кампании.

    Реализация: если у кампании уже есть сценарий, ЗАМЕНЯЕМ его новым
    (старый удаляется каскадом вместе с ролями/шагами — sceneriario_id в
    таблицах ролей/шагов идёт с ondelete=CASCADE через FK на scenarios.id).
    Флаг ``ai_generated`` и ``persons_count`` из тела применяются.
    """
    from modules.shilling.models import ShillingCampaign, ShillingScenario

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
