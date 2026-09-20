"""Роуты аккаунтов: CRUD, прогрев, история, действия (PROJECT-STAGES §6/§10).

Инварианты API-слоя:
* статус НИКОГДА не меняется напрямую — только через :class:`AccountStateMachine`
  (действия retire / acknowledge_ban) либо через очередь (login_start);
* фингерпринт-поля неизменяемы — PATCH их не принимает (schema ``extra=forbid``);
* ответы — read-схемы из ``core``.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.governor import get_health_governor
from api.deps.limits import enforce_limit
from api.deps.queue import get_publisher, get_task_queue
from worker.health.governor import Governor
from api.services import accounts as accounts_service
from core.enums import AccountStatus, Initiator, WarmingProfile
from core.queue import TaskQueue
from core.queue.publisher import Publisher
from core.queue.task_names import TaskName
from core.crypto import encrypt_password
from core.enums import BulkActionType
from core.repositories.account import AccountRepository
from core.repositories.account_health import AccountHealthRepository
from core.repositories.account_status_history import AccountStatusHistoryRepository
from core.repositories.bulk_job import BulkJobRepository
from core.repositories.persona import PersonaRepository
from core.repositories.warming_activity import WarmingActivityRepository
from core.schemas.bulk import BulkJobRead
from core.schemas.account import AccountRead, AccountUpdate
from core.schemas.account_health import AccountHealthRead
from core.schemas.history import AccountStatusHistoryRead
from core.schemas.warming import WarmingActivityRead
from modules.profiles.generator import (
    GeneratedProfile,
    ProfileGenerationError,
    default_generator,
)
from core.state_machine import AccountEvent, AccountStateMachine, TransitionError

router = APIRouter(
    prefix="/accounts", tags=["accounts"], dependencies=[Depends(require_user)]
)


# --- request-модели API (не доменные; фингерпринт/статус недопустимы) ---------


class AccountCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str
    proxy_id: int
    persona_id: Optional[int] = None
    warming_profile: WarmingProfile = WarmingProfile.MEDIUM


class AccountPatchRequest(BaseModel):
    # extra=forbid → device_model и прочий фингерпринт/статус в теле дают 422.
    model_config = ConfigDict(extra="forbid")

    phone: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    proxy_id: Optional[int] = None
    persona_id: Optional[int] = None
    # Этап 2: проект-группировка, роль, теги.
    project_id: Optional[int] = None
    role: Optional[str] = None
    tags: Optional[list[str]] = None


class WarmingProfilePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: WarmingProfile


def _get_account_or_404(session: Session, account_id: int):
    account = AccountRepository(session).get(account_id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"account {account_id} not found")
    return account


# --- CRUD --------------------------------------------------------------------


@router.get("", response_model=list[AccountRead])
def list_accounts(
    status: Optional[AccountStatus] = None,
    warming_profile: Optional[WarmingProfile] = None,
    project_id: Optional[int] = None,
    role: Optional[str] = None,
    tag: Optional[str] = None,
    session: Session = Depends(get_session),
) -> list[AccountRead]:
    accounts = accounts_service.list_accounts(
        session,
        status=status,
        warming_profile=warming_profile,
        project_id=project_id,
        role=role,
        tag=tag,
    )
    return [AccountRead.model_validate(a) for a in accounts]


@router.get("/{account_id}", response_model=AccountRead)
def get_account(account_id: int, session: Session = Depends(get_session)) -> AccountRead:
    return AccountRead.model_validate(_get_account_or_404(session, account_id))


@router.post("", response_model=AccountRead, status_code=status.HTTP_201_CREATED)
async def create_account(
    body: AccountCreateRequest,
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
    _limit: None = Depends(enforce_limit("accounts_max")),
) -> AccountRead:
    try:
        account = accounts_service.create_account(
            session,
            phone=body.phone,
            proxy_id=body.proxy_id,
            persona_id=body.persona_id,
            warming_profile=body.warming_profile,
        )
    except accounts_service.ProxyNotFoundError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    await task_queue.enqueue(TaskName.ACCOUNT_LOGIN_START, account.id)
    return AccountRead.model_validate(account)


@router.post(
    "/import-session", response_model=AccountRead, status_code=status.HTTP_201_CREATED
)
async def import_session_account(
    phone: str = Form(...),
    proxy_id: int = Form(...),
    persona_id: Optional[int] = Form(None),
    warming_profile: WarmingProfile = Form(WarmingProfile.MEDIUM),
    session_string: Optional[str] = Form(None),
    session_file: Optional[UploadFile] = File(None),
    session: Session = Depends(get_session),
    _limit: None = Depends(enforce_limit("accounts_max")),
) -> AccountRead:
    """Импорт аккаунта из готовой сессии: StringSession-строкой или .session-файлом.

    Сессия конвертируется (файл → строка, офлайн) и шифруется перед записью в БД
    (``session_enc``). Аккаунт сразу попадает в пул — код не требуется."""
    string = (session_string or "").strip()
    if not string and session_file is not None:
        try:
            string = accounts_service.session_file_to_string(await session_file.read())
        except accounts_service.SessionImportError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - битый файл → понятная 422
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"не удалось прочитать session-файл: {exc}",
            ) from exc
    if not string:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "нужна session-строка или .session-файл",
        )

    try:
        account = accounts_service.import_account_from_session(
            session,
            phone=phone,
            proxy_id=proxy_id,
            persona_id=persona_id,
            warming_profile=warming_profile,
            session_string=string,
        )
    except accounts_service.ProxyNotFoundError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return AccountRead.model_validate(account)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_account(
    account_id: int,
    session: Session = Depends(get_session),
) -> None:
    """Полное удаление аккаунта (в т.ч. выведенного) со всеми зависимостями."""
    if not accounts_service.delete_account(session, account_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"account {account_id} not found")


@router.patch("/{account_id}", response_model=AccountRead)
def patch_account(
    account_id: int,
    body: AccountPatchRequest,
    session: Session = Depends(get_session),
) -> AccountRead:
    account = accounts_service.update_account(
        session,
        account_id,
        AccountUpdate(**body.model_dump(exclude_unset=True)),
    )
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"account {account_id} not found")
    return AccountRead.model_validate(account)


# --- Прогрев -----------------------------------------------------------------


@router.get("/{account_id}/warming", response_model=list[WarmingActivityRead])
def list_warming(
    account_id: int, session: Session = Depends(get_session)
) -> list[WarmingActivityRead]:
    _get_account_or_404(session, account_id)
    activities = WarmingActivityRepository(session).list_by_account(account_id)
    return [WarmingActivityRead.model_validate(a) for a in activities]


@router.patch("/{account_id}/warming", response_model=AccountRead)
def set_warming_profile(
    account_id: int,
    body: WarmingProfilePatchRequest,
    session: Session = Depends(get_session),
) -> AccountRead:
    account = accounts_service.update_account(
        session, account_id, AccountUpdate(warming_profile=body.profile)
    )
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"account {account_id} not found")
    return AccountRead.model_validate(account)


# --- История стадий ----------------------------------------------------------


@router.get("/{account_id}/history", response_model=list[AccountStatusHistoryRead])
def list_history(
    account_id: int, session: Session = Depends(get_session)
) -> list[AccountStatusHistoryRead]:
    _get_account_or_404(session, account_id)
    records = AccountStatusHistoryRepository(session).list_by_account(account_id)
    return [AccountStatusHistoryRead.model_validate(r) for r in records]


# --- Действия (через state machine) ------------------------------------------


def _transition(
    session: Session,
    publisher: Optional[Publisher],
    account_id: int,
    event: AccountEvent,
) -> AccountRead:
    machine = AccountStateMachine(session, publisher)
    try:
        account = machine.transition(account_id, event, Initiator.USER)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except TransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return AccountRead.model_validate(account)


@router.post("/{account_id}/actions/retire", response_model=AccountRead)
def retire_account(
    account_id: int,
    session: Session = Depends(get_session),
    publisher: Optional[Publisher] = Depends(get_publisher),
) -> AccountRead:
    return _transition(session, publisher, account_id, AccountEvent.RETIRE)


@router.post("/{account_id}/actions/restore", response_model=AccountRead)
def restore_account(
    account_id: int,
    session: Session = Depends(get_session),
    publisher: Optional[Publisher] = Depends(get_publisher),
) -> AccountRead:
    """Возврат выведенного аккаунта в пул (RETIRED → POOL)."""
    return _transition(session, publisher, account_id, AccountEvent.RESTORE)


@router.post("/{account_id}/actions/acknowledge_ban", response_model=AccountRead)
def acknowledge_ban(
    account_id: int,
    session: Session = Depends(get_session),
    publisher: Optional[Publisher] = Depends(get_publisher),
) -> AccountRead:
    return _transition(session, publisher, account_id, AccountEvent.ACKNOWLEDGE_BAN)


# --- Health (этап 4 УТП) -----------------------------------------------------


class HealthCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_spam: bool = False


class HealthCheckBulkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_ids: list[int]
    include_spam: bool = False


def _probes_for(include_spam: bool) -> list[str]:
    probes = ["session", "profile"]
    if include_spam:
        probes.append("spamblock")
    return probes


@router.get("/health/at-risk", response_model=list[AccountHealthRead])
def list_at_risk(
    max_score: int = 40,
    limit: int = 100,
    session: Session = Depends(get_session),
) -> list[AccountHealthRead]:
    """Список аккаунтов с низким health_score (сортировка по возрастанию)."""
    rows = AccountHealthRepository(session).list_at_risk(max_score=max_score, limit=limit)
    return [AccountHealthRead.model_validate(r) for r in rows]


@router.get("/{account_id}/health", response_model=AccountHealthRead)
def get_account_health(
    account_id: int, session: Session = Depends(get_session)
) -> AccountHealthRead:
    _get_account_or_404(session, account_id)
    snapshot = AccountHealthRepository(session).get_or_create(account_id)
    return AccountHealthRead.model_validate(snapshot)


@router.post("/{account_id}/health/check", status_code=status.HTTP_202_ACCEPTED)
async def enqueue_health_check(
    account_id: int,
    body: HealthCheckRequest,
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
    governor: Governor = Depends(get_health_governor),
) -> dict[str, Any]:
    _get_account_or_404(session, account_id)
    reserved = await governor.check_and_reserve(account_id, "health_check")
    if not reserved:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"health-check rate limit exceeded for account {account_id}",
        )
    job_id = await task_queue.enqueue(
        TaskName.HEALTH_CHECK_ACCOUNT, account_id, _probes_for(body.include_spam)
    )
    return {"job_id": job_id}


# --- Profile preview (этап 6 УТП) --------------------------------------------


class ProfilePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm_provider: str = "deepseek"


class ProfilePreviewResponse(BaseModel):
    first_name: str
    last_name: str = ""
    bio: str = ""
    username_candidates: list[str] = []


@router.post(
    "/{account_id}/profile/generate-preview",
    response_model=ProfilePreviewResponse,
)
async def generate_profile_preview(
    account_id: int,
    body: ProfilePreviewRequest,
    session: Session = Depends(get_session),
) -> ProfilePreviewResponse:
    """Возвращает сгенерированный по персоне профиль БЕЗ применения к Telegram.

    Нужен для превью в mini-app перед bulk-применением: пользователь смотрит,
    что LLM выдал по одному акку, и запускает bulk (или редактирует и
    применяет через ``apply_profile``)."""
    account = _get_account_or_404(session, account_id)
    if account.persona_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "account has no persona — attach one before generating profile",
        )
    persona = PersonaRepository(session).get(account.persona_id)
    if persona is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"persona {account.persona_id} not found",
        )
    try:
        generated: GeneratedProfile = await default_generator(body.llm_provider).generate(
            persona
        )
    except ProfileGenerationError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"profile generation failed: {exc}",
        ) from exc
    return ProfilePreviewResponse(**generated.as_dict())


# --- Security: bulk 2FA (этап 7 УТП) -----------------------------------------


class Set2FABulkRequest(BaseModel):
    """Plaintext-обёртка над bulk-action ``set_2fa``.

    В отличие от общего ``POST /bulk-jobs`` — принимает открытый пароль и
    шифрует его до записи в БД (в ``bulk_jobs.payload`` попадает уже
    ``password_enc_b64``, plaintext дальше API не идёт).
    """

    model_config = ConfigDict(extra="forbid")

    account_ids: list[int]
    mode: str = "set_or_change"  # см. Set2FAPayload
    password: Optional[str] = None
    hint: Optional[str] = None
    email: Optional[str] = None


@router.post(
    "/bulk/set-2fa",
    response_model=BulkJobRead,
    status_code=status.HTTP_201_CREATED,
)
async def bulk_set_2fa(
    body: Set2FABulkRequest,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
) -> BulkJobRead:
    if body.mode not in ("set_or_change", "remove"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"unknown mode: {body.mode!r}; expected set_or_change|remove",
        )
    if body.mode == "set_or_change" and not body.password:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "password is required for mode=set_or_change",
        )
    if not body.account_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "account_ids is empty")

    repo_accounts = AccountRepository(session)
    missing = [aid for aid in body.account_ids if repo_accounts.get(aid) is None]
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"unknown account ids: {missing}",
        )

    # Шифруем ДО записи в БД. Plaintext исчезает вместе с request scope'ом.
    payload: dict[str, Any] = {"mode": body.mode}
    if body.password:
        import base64

        enc = encrypt_password(body.password.encode("utf-8"))
        payload["password_enc_b64"] = base64.b64encode(enc).decode("ascii")
    if body.hint is not None:
        payload["hint"] = body.hint
    if body.email is not None:
        payload["email"] = body.email

    repo = BulkJobRepository(session)
    job = repo.create(
        action_type=BulkActionType.SET_2FA.value,
        payload=payload,
        initiator=user_id,
        account_ids=body.account_ids,
    )
    session.commit()
    await task_queue.enqueue(TaskName.BULK_DISPATCH, job.id)
    return BulkJobRead.model_validate(job)


@router.post("/health/check-bulk", status_code=status.HTTP_202_ACCEPTED)
async def enqueue_health_check_bulk(
    body: HealthCheckBulkRequest,
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
    governor: Governor = Depends(get_health_governor),
) -> dict[str, Any]:
    if not body.account_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "account_ids is empty")
    # Валидируем существование аккаунтов до постановки задач.
    repo = AccountRepository(session)
    missing = [aid for aid in body.account_ids if repo.get(aid) is None]
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"unknown account ids: {missing}",
        )

    probes = _probes_for(body.include_spam)
    enqueued: list[dict[str, Any]] = []
    throttled: list[int] = []
    for aid in body.account_ids:
        # Rate-limit по аккаунту, а не по пользователю: защищает от «прожига»
        # одной карточки повторными bulk-проверками.
        if not await governor.check_and_reserve(aid, "health_check"):
            throttled.append(aid)
            continue
        job_id = await task_queue.enqueue(TaskName.HEALTH_CHECK_ACCOUNT, aid, probes)
        enqueued.append({"account_id": aid, "job_id": job_id})
    return {"enqueued": enqueued, "throttled": throttled}
