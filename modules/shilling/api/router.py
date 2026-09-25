"""Роутер модуля НейроШиллинг.

Префикс ``/modules/shilling``. Тут — только CRUD кампаний (промпт 2.1);
сценарии/роли/шаги, аккаунты, цели, ЧС, readiness/stats/start/stop
подключаются следующими промптами (2.2–2.4).

Монтирование — в ``api/routing.py`` (единственный список роутеров).
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.queue import get_task_queue
from core.queue import TaskQueue
from core.queue.task_names import TaskName
from modules.shilling.api import service
from modules.shilling.repositories import (
    BlacklistRepository,
    CampaignAccountRepository,
    CampaignRepository,
    CampaignTargetRepository,
    ExecutionLogRepository,
    ScenarioRepository,
    ScenarioRoleRepository,
    ScenarioStepRepository,
)
from modules.shilling.schemas import (
    AttachAccountRequest,
    BlacklistCreate,
    BlacklistRead,
    CampaignAccountRead,
    CampaignAccountUpdate,
    CampaignCreate,
    CampaignReadiness,
    CampaignRead,
    CampaignStats,
    CampaignUpdate,
    ExecutionLogRead,
    GeneratedScenarioRead,
    RoleCreate,
    ScenarioGenerateRequest,
    RoleRead,
    RoleUpdate,
    ScenarioCreate,
    ScenarioRead,
    ScenarioUpdate,
    StepCreate,
    StepRead,
    StepReorderRequest,
    StepUpdate,
    TargetBulkCreate,
    TargetRead,
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


@router.post(
    "/campaigns/{campaign_id}/scenario/generate",
    response_model=GeneratedScenarioRead,
)
async def generate_scenario(
    campaign_id: int,
    body: ScenarioGenerateRequest,
    session: Session = Depends(get_session),
) -> GeneratedScenarioRead:
    """ИИ-генерация черновика сценария. НЕ сохраняет — фронт применяет через PUT."""
    from modules.shilling.llm import (
        GeneratedRole,
        ScenarioGenerationError,
        ScenarioGenerator,
    )
    from worker.llm import get_provider

    campaign = CampaignRepository(session).get(campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")

    brand = body.brand_name or campaign.brand_name
    if not brand:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "brand_name is required (pass it or set it on the campaign)",
        )

    forced_roles = (
        [GeneratedRole(name=r.name, character=r.character) for r in body.roles]
        if body.roles
        else None
    )
    generator = ScenarioGenerator(get_provider(campaign.llm_provider))
    try:
        draft = await generator.generate(
            topic=body.topic,
            brand_name=brand,
            persons_count=body.persons_count,
            steps_count=body.steps_count,
            roles=forced_roles,
        )
    except ScenarioGenerationError as exc:
        # 502: внешний LLM не дал пригодного результата (не вина клиента).
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    return GeneratedScenarioRead(
        roles=[{"name": r.name, "character": r.character} for r in draft.roles],
        steps=[
            {"role": s.role, "text": s.text, "reply_to_step": s.reply_to_step}
            for s in draft.steps
        ],
    )


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


# --- Аккаунты кампании -------------------------------------------------------


@router.get(
    "/campaigns/{campaign_id}/accounts",
    response_model=list[CampaignAccountRead],
)
def list_campaign_accounts(
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
) -> CampaignAccountRead:
    try:
        link = service.attach_account(
            session,
            campaign_id,
            body.account_id,
            role_id=body.role_id,
            is_reserve=body.is_reserve,
        )
    except service.ShillingNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except service.ShillingConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except service.ShillingValidation as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    session.commit()
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
    try:
        link = service.update_account_link(session, campaign_id, account_id, body)
    except service.ShillingNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except service.ShillingValidation as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
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
) -> None:
    try:
        service.detach_account(session, campaign_id, account_id)
    except service.ShillingNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    session.commit()


# --- Целевые каналы ----------------------------------------------------------


@router.get("/campaigns/{campaign_id}/targets", response_model=list[TargetRead])
def list_targets(
    campaign_id: int, session: Session = Depends(get_session)
) -> list[TargetRead]:
    if CampaignRepository(session).get(campaign_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    items = CampaignTargetRepository(session).list_by_campaign(campaign_id)
    return [TargetRead.model_validate(i) for i in items]


@router.post(
    "/campaigns/{campaign_id}/targets",
    response_model=list[TargetRead],
    status_code=status.HTTP_201_CREATED,
)
def add_targets(
    campaign_id: int,
    body: TargetBulkCreate,
    session: Session = Depends(get_session),
) -> list[TargetRead]:
    """Bulk-добавление: нормализация + дедуп. Возвращает только созданные."""
    try:
        created = service.add_targets_bulk(session, campaign_id, body.raw_inputs)
    except service.ShillingNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    session.commit()
    return [TargetRead.model_validate(t) for t in created]


@router.delete(
    "/campaigns/{campaign_id}/targets/{target_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def delete_target(
    campaign_id: int,
    target_id: int,
    session: Session = Depends(get_session),
) -> None:
    if not CampaignTargetRepository(session).delete(campaign_id, target_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "target not found")
    session.commit()


# --- Чёрный список -----------------------------------------------------------


@router.get(
    "/campaigns/{campaign_id}/blacklist", response_model=list[BlacklistRead]
)
def list_blacklist(
    campaign_id: int, session: Session = Depends(get_session)
) -> list[BlacklistRead]:
    if CampaignRepository(session).get(campaign_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    items = BlacklistRepository(session).list_by_campaign(campaign_id)
    return [BlacklistRead.model_validate(i) for i in items]


@router.post(
    "/campaigns/{campaign_id}/blacklist",
    response_model=BlacklistRead,
    status_code=status.HTTP_201_CREATED,
)
def add_blacklist(
    campaign_id: int,
    body: BlacklistCreate,
    session: Session = Depends(get_session),
) -> BlacklistRead:
    """Ручное добавление в ЧС (auto=False). Воркер добавляет с auto=True."""
    from sqlalchemy.exc import IntegrityError

    if CampaignRepository(session).get(campaign_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    try:
        entry = BlacklistRepository(session).create(campaign_id, body, auto=False)
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "already blacklisted") from None
    return BlacklistRead.model_validate(entry)


@router.delete(
    "/campaigns/{campaign_id}/blacklist/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def remove_blacklist(
    campaign_id: int,
    entry_id: int,
    session: Session = Depends(get_session),
) -> None:
    if not BlacklistRepository(session).delete(campaign_id, entry_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "blacklist entry not found")
    session.commit()


# --- Готовность / статистика / логи -----------------------------------------


@router.get(
    "/campaigns/{campaign_id}/readiness", response_model=CampaignReadiness
)
def get_readiness(
    campaign_id: int, session: Session = Depends(get_session)
) -> CampaignReadiness:
    try:
        return service.compute_readiness(session, campaign_id)
    except service.ShillingNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.get("/campaigns/{campaign_id}/stats", response_model=CampaignStats)
def get_stats(
    campaign_id: int, session: Session = Depends(get_session)
) -> CampaignStats:
    try:
        return service.compute_stats(session, campaign_id)
    except service.ShillingNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.get("/campaigns/{campaign_id}/logs", response_model=list[ExecutionLogRead])
def list_logs(
    campaign_id: int,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[ExecutionLogRead]:
    if CampaignRepository(session).get(campaign_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    logs = ExecutionLogRepository(session).list_by_campaign(
        campaign_id, status=status_filter, limit=limit, offset=offset
    )
    return [ExecutionLogRead.model_validate(log) for log in logs]


# --- Жизненный цикл: start / stop / dry-run ---------------------------------


@router.post("/campaigns/{campaign_id}/start", response_model=CampaignRead)
async def start_campaign(
    campaign_id: int,
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
) -> CampaignRead:
    """Валидирует готовность, переводит в running и ставит задачу оркестратора."""
    try:
        service.prepare_start(session, campaign_id)
    except service.ShillingNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except service.ShillingConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except service.ShillingValidation as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    session.commit()
    # Задача публикуется ПОСЛЕ commit'а: смена статуса уже зафиксирована.
    await task_queue.enqueue(TaskName.SHILLING_START_CAMPAIGN, campaign_id)
    campaign = CampaignRepository(session).get(campaign_id)
    return CampaignRead.model_validate(campaign)


@router.post("/campaigns/{campaign_id}/stop", response_model=CampaignRead)
def stop_campaign(
    campaign_id: int,
    session: Session = Depends(get_session),
) -> CampaignRead:
    """Переводит кампанию в paused. Задачи-в-полёте сами проверяют статус."""
    try:
        service.prepare_stop(session, campaign_id)
    except service.ShillingNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    session.commit()
    campaign = CampaignRepository(session).get(campaign_id)
    return CampaignRead.model_validate(campaign)


@router.post(
    "/campaigns/{campaign_id}/dry-run", status_code=status.HTTP_202_ACCEPTED
)
async def dry_run_campaign(
    campaign_id: int,
    test_target: str = Query(..., description="@username или t.me/... тест-чата"),
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
) -> dict[str, str]:
    """Ставит задачу сухого прогона. Результат забирается по SSE (промпт 4.5).

    Возвращает job_id, по которому фронт подпишется на поток событий.
    """
    if CampaignRepository(session).get(campaign_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"campaign {campaign_id} not found")
    job_id = uuid.uuid4().hex
    await task_queue.enqueue(
        TaskName.SHILLING_DRY_RUN, campaign_id, test_target, job_id
    )
    return {"job_id": job_id}
