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
from modules.shilling.api import service
from modules.shilling.repositories import (
    CampaignRepository,
    ScenarioRepository,
    ScenarioRoleRepository,
    ScenarioStepRepository,
)
from modules.shilling.schemas import (
    CampaignCreate,
    CampaignRead,
    CampaignUpdate,
    RoleCreate,
    RoleRead,
    RoleUpdate,
    ScenarioCreate,
    ScenarioRead,
    ScenarioUpdate,
    StepCreate,
    StepRead,
    StepReorderRequest,
    StepUpdate,
)

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


# --- Сценарий кампании (GET / PUT) -------------------------------------------


@router.get("/campaigns/{campaign_id}/scenario", response_model=ScenarioRead)
def get_campaign_scenario(
    campaign_id: int, session: Session = Depends(get_session)
) -> ScenarioRead:
    if CampaignRepository(session).get(campaign_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    scenario = ScenarioRepository(session).get_by_campaign(campaign_id)
    if scenario is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"campaign {campaign_id} has no scenario",
        )
    return ScenarioRead.model_validate(scenario)


@router.put("/campaigns/{campaign_id}/scenario", response_model=ScenarioRead)
def put_campaign_scenario(
    campaign_id: int,
    body: ScenarioCreate,
    session: Session = Depends(get_session),
) -> ScenarioRead:
    """Создать или заменить сценарий кампании (старый удаляется каскадом)."""
    try:
        scenario = service.upsert_scenario_for_campaign(session, campaign_id, body)
    except service.ShillingNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    session.commit()
    return ScenarioRead.model_validate(scenario)


# --- Роли сценария -----------------------------------------------------------


def _require_scenario(session: Session, scenario_id: int) -> None:
    if ScenarioRepository(session).get(scenario_id) is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"scenario {scenario_id} not found"
        )


@router.get("/scenarios/{scenario_id}/roles", response_model=list[RoleRead])
def list_roles(
    scenario_id: int, session: Session = Depends(get_session)
) -> list[RoleRead]:
    _require_scenario(session, scenario_id)
    roles = ScenarioRoleRepository(session).list_by_scenario(scenario_id)
    return [RoleRead.model_validate(r) for r in roles]


@router.post(
    "/scenarios/{scenario_id}/roles",
    response_model=RoleRead,
    status_code=status.HTTP_201_CREATED,
)
def create_role(
    scenario_id: int,
    body: RoleCreate,
    session: Session = Depends(get_session),
) -> RoleRead:
    _require_scenario(session, scenario_id)
    role = ScenarioRoleRepository(session).create(scenario_id, body)
    session.commit()
    return RoleRead.model_validate(role)


@router.patch("/scenarios/{scenario_id}/roles/{role_id}", response_model=RoleRead)
def patch_role(
    scenario_id: int,
    role_id: int,
    body: RoleUpdate,
    session: Session = Depends(get_session),
) -> RoleRead:
    _require_scenario(session, scenario_id)
    role_repo = ScenarioRoleRepository(session)
    existing = role_repo.get(role_id)
    if existing is None or existing.scenario_id != scenario_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"role {role_id} not found in scenario {scenario_id}",
        )
    role = role_repo.update(role_id, body)
    session.commit()
    return RoleRead.model_validate(role)


@router.delete(
    "/scenarios/{scenario_id}/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def delete_role_endpoint(
    scenario_id: int,
    role_id: int,
    session: Session = Depends(get_session),
) -> None:
    _require_scenario(session, scenario_id)
    try:
        service.delete_role(session, scenario_id, role_id)
    except service.ShillingNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except service.ShillingConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    session.commit()


# --- Шаги сценария -----------------------------------------------------------


@router.get("/scenarios/{scenario_id}/steps", response_model=list[StepRead])
def list_steps(
    scenario_id: int, session: Session = Depends(get_session)
) -> list[StepRead]:
    _require_scenario(session, scenario_id)
    steps = ScenarioStepRepository(session).list_by_scenario(scenario_id)
    return [StepRead.model_validate(s) for s in steps]


@router.post(
    "/scenarios/{scenario_id}/steps",
    response_model=StepRead,
    status_code=status.HTTP_201_CREATED,
)
def create_step(
    scenario_id: int,
    body: StepCreate,
    session: Session = Depends(get_session),
) -> StepRead:
    _require_scenario(session, scenario_id)
    # role_id должен принадлежать этому сценарию (иначе валидация фейлится
    # позже FK-констрейнтом с невнятной ошибкой — ловим здесь явно).
    role = ScenarioRoleRepository(session).get(body.role_id)
    if role is None or role.scenario_id != scenario_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"role {body.role_id} does not belong to scenario {scenario_id}",
        )
    # reply_to_step_id (если задан) — тоже должен быть из этого сценария.
    if body.reply_to_step_id is not None:
        ref = ScenarioStepRepository(session).get(body.reply_to_step_id)
        if ref is None or ref.scenario_id != scenario_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"reply_to_step_id {body.reply_to_step_id} is not in scenario {scenario_id}",
            )
    step = ScenarioStepRepository(session).create(scenario_id, body)
    session.commit()
    return StepRead.model_validate(step)


@router.patch(
    "/scenarios/{scenario_id}/steps/{step_id}", response_model=StepRead
)
def patch_step(
    scenario_id: int,
    step_id: int,
    body: StepUpdate,
    session: Session = Depends(get_session),
) -> StepRead:
    _require_scenario(session, scenario_id)
    step_repo = ScenarioStepRepository(session)
    existing = step_repo.get(step_id)
    if existing is None or existing.scenario_id != scenario_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"step {step_id} not found in scenario {scenario_id}",
        )
    # Проверки принадлежности новой role_id / reply_to_step_id этому сценарию.
    if body.role_id is not None:
        role = ScenarioRoleRepository(session).get(body.role_id)
        if role is None or role.scenario_id != scenario_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"role {body.role_id} does not belong to scenario {scenario_id}",
            )
    if body.reply_to_step_id is not None:
        ref = step_repo.get(body.reply_to_step_id)
        if ref is None or ref.scenario_id != scenario_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"reply_to_step_id {body.reply_to_step_id} is not in scenario {scenario_id}",
            )
        if body.reply_to_step_id == step_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "step cannot reply to itself"
            )
    step = step_repo.update(step_id, body)
    session.commit()
    return StepRead.model_validate(step)


@router.delete(
    "/scenarios/{scenario_id}/steps/{step_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def delete_step_endpoint(
    scenario_id: int,
    step_id: int,
    session: Session = Depends(get_session),
) -> None:
    _require_scenario(session, scenario_id)
    try:
        service.delete_step(session, scenario_id, step_id)
    except service.ShillingNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    session.commit()


@router.post(
    "/scenarios/{scenario_id}/steps/reorder", status_code=status.HTTP_204_NO_CONTENT
)
def reorder_steps_endpoint(
    scenario_id: int,
    body: StepReorderRequest,
    session: Session = Depends(get_session),
) -> None:
    try:
        service.reorder_steps(session, scenario_id, body.step_ids)
    except service.ShillingNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except service.ShillingValidation as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    session.commit()
