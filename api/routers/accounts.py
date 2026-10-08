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
from core.enums import AccountStatus, Initiator, WarmingActionType, WarmingProfile
from core.queue import TaskQueue
from core.queue.publisher import Publisher
from core.queue.task_names import TaskName
from core.crypto import CryptoError, decrypt_session, encrypt_password
from core.enums import BulkActionType
from core.repositories.account import AccountRepository
from core.repositories.account_health import AccountHealthRepository
from core.repositories.account_status_history import AccountStatusHistoryRepository
from core.repositories.bulk_job import BulkJobRepository
from core.repositories.persona import PersonaRepository
from core.repositories.project_channel import ProjectChannelRepository
from core.repositories.warming_activity import WarmingActivityRepository
from core.schemas.bulk import BulkJobRead
from core.schemas.account import AccountRead, AccountUpdate
from core.schemas.account_health import AccountHealthRead
from core.schemas.history import AccountStatusHistoryRead
from core.schemas.project_channel import ProjectChannelRead
from modules.commenting.repositories.comment_log import CommentLogRepository
from modules.commenting.schemas.comment_log import CommentLogRead
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


class PhoneCheckResult(BaseModel):
    """Результат pre-check номера перед добавлением аккаунта."""

    phone: str
    normalized: str
    exists: bool


@router.get("/check-phone", response_model=PhoneCheckResult)
def check_phone(
    phone: str,
    session: Session = Depends(get_session),
) -> PhoneCheckResult:
    """Проверяет, занят ли номер, ещё на этапе ввода — чтобы UI показал
    «такой номер уже есть» до отправки кода, а не ловил 409 после."""
    return PhoneCheckResult(
        phone=phone,
        normalized=accounts_service.normalize_phone(phone),
        exists=accounts_service.phone_exists(session, phone),
    )


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
    except accounts_service.PhoneAlreadyExistsError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "reason": "phone_already_exists",
                "phone": exc.phone,
                "message": "Аккаунт с таким номером уже есть в системе.",
            },
        ) from exc

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
    except accounts_service.PhoneAlreadyExistsError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "reason": "phone_already_exists",
                "phone": exc.phone,
                "message": "Аккаунт с таким номером уже есть в системе.",
            },
        ) from exc
    return AccountRead.model_validate(account)


@router.post(
    "/import-tdata", response_model=AccountRead, status_code=status.HTTP_201_CREATED
)
async def import_tdata_account(
    phone: str = Form(...),
    proxy_id: int = Form(...),
    persona_id: Optional[int] = Form(None),
    warming_profile: WarmingProfile = Form(WarmingProfile.MEDIUM),
    tdata_zip: UploadFile = File(..., description="ZIP с папкой tdata"),
    session: Session = Depends(get_session),
    _limit: None = Depends(enforce_limit("accounts_max")),
) -> AccountRead:
    """Импорт аккаунта из TData (Telegram Desktop): ZIP конвертируется офлайн в
    StringSession, шифруется и сохраняется. Аккаунт сразу попадает в пул."""
    try:
        string = accounts_service.tdata_zip_to_string(await tdata_zip.read())
    except accounts_service.SessionImportError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

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
    except accounts_service.PhoneAlreadyExistsError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "reason": "phone_already_exists",
                "phone": exc.phone,
                "message": "Аккаунт с таким номером уже есть в системе.",
            },
        ) from exc
    return AccountRead.model_validate(account)


@router.post("/bulk-import")
async def bulk_import_accounts(
    archive: UploadFile = File(..., description="ZIP с .session-файлами"),
    mapping: UploadFile = File(..., description="CSV: phone,proxy_id[,warming_profile,persona_id,project_id,role,tags]"),
    session: Session = Depends(get_session),
) -> dict:
    """Массовый импорт из архива + CSV (этап 1).

    Best-effort: ошибка одной строки не роняет остальные. В ответе — что
    успешно, что пропущено и почему. Тарифный лимит `accounts_max` здесь НЕ
    применяется через enforce_limit (у зависимости нет счёта заранее);
    вместо этого сам сервис откатывает лишние вставки на IntegrityError.
    """
    from api.services.bulk_import import bulk_import

    archive_bytes = await archive.read()
    csv_bytes = await mapping.read()
    try:
        report = bulk_import(session, archive_bytes=archive_bytes, csv_bytes=csv_bytes)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return report.as_dict()


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


# --- Конструктор сценариев прогрева (кастом поверх пресета) -------------------

_WARMING_ACTION_VALUES = {a.value for a in WarmingActionType}


class WarmingScenarioBody(BaseModel):
    """Кастомный сценарий прогрева аккаунта. Любое поле опционально —
    незаданное наследуется от пресета (minimal/medium/dense)."""

    model_config = ConfigDict(extra="forbid")

    interval_hours_min: Optional[float] = None
    interval_hours_max: Optional[float] = None
    actions_min: Optional[int] = None
    actions_max: Optional[int] = None
    # action_value -> вес (>=0); 0 = действие выключено.
    action_weights: Optional[dict[str, float]] = None
    ready_actions: Optional[int] = None
    ready_days: Optional[int] = None

    def _validate(self) -> None:
        if self.interval_hours_min is not None and self.interval_hours_min <= 0:
            raise ValueError("interval_hours_min must be > 0")
        if (
            self.interval_hours_min is not None
            and self.interval_hours_max is not None
            and self.interval_hours_max < self.interval_hours_min
        ):
            raise ValueError("interval_hours_max must be >= interval_hours_min")
        if self.actions_min is not None and self.actions_min < 1:
            raise ValueError("actions_min must be >= 1")
        if (
            self.actions_min is not None
            and self.actions_max is not None
            and self.actions_max < self.actions_min
        ):
            raise ValueError("actions_max must be >= actions_min")
        if self.action_weights is not None:
            for key, val in self.action_weights.items():
                if key not in _WARMING_ACTION_VALUES:
                    raise ValueError(f"unknown action: {key}")
                if val < 0:
                    raise ValueError(f"weight for {key} must be >= 0")
        for field_name in ("ready_actions", "ready_days"):
            v = getattr(self, field_name)
            if v is not None and v < 1:
                raise ValueError(f"{field_name} must be >= 1")

    def to_meta(self) -> dict:
        """В формат ``accounts.meta['warming_scenario']`` (только заданные поля)."""
        out: dict[str, Any] = {}
        if self.interval_hours_min is not None and self.interval_hours_max is not None:
            out["interval_hours"] = [self.interval_hours_min, self.interval_hours_max]
        if self.actions_min is not None and self.actions_max is not None:
            out["actions_per_batch"] = [self.actions_min, self.actions_max]
        if self.action_weights:
            out["action_weights"] = self.action_weights
        if self.ready_actions is not None:
            out["ready_actions"] = self.ready_actions
        if self.ready_days is not None:
            out["ready_days"] = self.ready_days
        return out


def _scenario_to_body(meta: dict) -> WarmingScenarioBody:
    raw = (meta or {}).get("warming_scenario") or {}
    iv = raw.get("interval_hours") or [None, None]
    ab = raw.get("actions_per_batch") or [None, None]
    return WarmingScenarioBody(
        interval_hours_min=iv[0],
        interval_hours_max=iv[1],
        actions_min=ab[0],
        actions_max=ab[1],
        action_weights=raw.get("action_weights"),
        ready_actions=raw.get("ready_actions"),
        ready_days=raw.get("ready_days"),
    )


@router.get("/{account_id}/warming-scenario", response_model=WarmingScenarioBody)
def get_warming_scenario(
    account_id: int, session: Session = Depends(get_session)
) -> WarmingScenarioBody:
    """Текущий кастомный сценарий прогрева (пустой = работает пресет)."""
    account = _get_account_or_404(session, account_id)
    return _scenario_to_body(account.meta or {})


@router.put("/{account_id}/warming-scenario", response_model=WarmingScenarioBody)
def put_warming_scenario(
    account_id: int,
    body: WarmingScenarioBody,
    session: Session = Depends(get_session),
) -> WarmingScenarioBody:
    """Сохранить кастомный сценарий прогрева в ``accounts.meta``."""
    account = _get_account_or_404(session, account_id)
    try:
        body._validate()
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    meta = dict(account.meta or {})
    scenario = body.to_meta()
    if scenario:
        meta["warming_scenario"] = scenario
    else:
        meta.pop("warming_scenario", None)
    account.meta = meta  # reassign → SQLAlchemy зафиксирует изменение JSON
    session.commit()
    session.refresh(account)
    return _scenario_to_body(account.meta or {})


@router.delete(
    "/{account_id}/warming-scenario",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def delete_warming_scenario(
    account_id: int, session: Session = Depends(get_session)
) -> None:
    """Сбросить сценарий — прогрев вернётся к пресету."""
    account = _get_account_or_404(session, account_id)
    if account.meta and "warming_scenario" in account.meta:
        meta = dict(account.meta)
        meta.pop("warming_scenario", None)
        account.meta = meta
        session.commit()


# --- История стадий ----------------------------------------------------------


@router.get("/{account_id}/history", response_model=list[AccountStatusHistoryRead])
def list_history(
    account_id: int, session: Session = Depends(get_session)
) -> list[AccountStatusHistoryRead]:
    _get_account_or_404(session, account_id)
    records = AccountStatusHistoryRepository(session).list_by_account(account_id)
    return [AccountStatusHistoryRead.model_validate(r) for r in records]


# --- Созданные каналы аккаунта («Управление аккаунтом», этап 1) ---------------


@router.get("/{account_id}/project-channels", response_model=list[ProjectChannelRead])
def list_project_channels(
    account_id: int, session: Session = Depends(get_session)
) -> list[ProjectChannelRead]:
    """Каналы/супергруппы, созданные этим аккаунтом (``project_channels``).

    Пишутся bulk-action ``create_channel``; UI карточки аккаунта по этому
    списку рендерит управление постами (``manage_channel_post``)."""
    _get_account_or_404(session, account_id)
    rows = ProjectChannelRepository(session).list_for_account(account_id)
    return [ProjectChannelRead.model_validate(r) for r in rows]


# --- Журнал аккаунта («Логи», этап 3) ----------------------------------------


@router.get("/{account_id}/comment-logs", response_model=list[CommentLogRead])
def list_account_comment_logs(
    account_id: int,
    limit: int = 50,
    session: Session = Depends(get_session),
) -> list[CommentLogRead]:
    """История комментариев аккаунта: что запостил, где, со статусом/ошибкой.

    В поле ``error`` оседают ответы Telegram API (``FLOOD_WAIT_X`` и т.п.) —
    UI подсвечивает их во вкладке «Логи»."""
    _get_account_or_404(session, account_id)
    rows = CommentLogRepository(session).list_by_account(account_id, limit=limit)
    return [CommentLogRead.model_validate(r) for r in rows]


# --- Экспорт сессий (этап 3) --------------------------------------------------


class ExportSessionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_ids: list[int]


class ExportedSession(BaseModel):
    account_id: int
    phone: str
    session_string: str


@router.post("/export-sessions", response_model=list[ExportedSession])
def export_sessions(
    body: ExportSessionsRequest,
    session: Session = Depends(get_session),
) -> list[ExportedSession]:
    """Экспорт StringSession выбранных аккаунтов (этап 3, bulk-action «Экспорт»).

    Расшифровываем ``session_enc`` и отдаём строкой — для бэкапа/переноса.
    Битые/нерасшифровываемые сессии пропускаем (best-effort)."""
    if not body.account_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "account_ids is empty")
    repo = AccountRepository(session)
    out: list[ExportedSession] = []
    for aid in body.account_ids:
        account = repo.get(aid)
        if account is None or not account.session_enc:
            continue
        try:
            session_string = decrypt_session(account.session_enc).decode("utf-8")
        except (CryptoError, ValueError, UnicodeDecodeError):
            continue
        if session_string:
            out.append(
                ExportedSession(
                    account_id=aid, phone=account.phone, session_string=session_string
                )
            )
    return out


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


class RecoveryEmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str
    password: str


class RecoveryEmailConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str


class RecoveryEmailState(BaseModel):
    email: Optional[str] = None
    pending_email: Optional[str] = None
    code_length: Optional[int] = None
    confirmed_at: Optional[str] = None


@router.post(
    "/{account_id}/2fa/recovery-email/request",
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_recovery_email(
    account_id: int,
    body: RecoveryEmailRequest,
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
) -> dict[str, Any]:
    """Инициировать привязку recovery-email к 2FA (этап 7, backlog #1).

    Шифруем пароль ДО постановки в очередь: Telethon-worker получит
    зашифрованный blob и вернёт результат в pub/sub канал
    ``security.recovery_email_updated``.
    """
    _get_account_or_404(session, account_id)
    if not body.email or "@" not in body.email:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid email")
    if not body.password:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "current password required"
        )
    import base64

    password_enc = encrypt_password(body.password.encode("utf-8"))
    password_enc_b64 = base64.b64encode(password_enc).decode("ascii")

    await task_queue.enqueue(
        TaskName.SECURITY_REQUEST_RECOVERY_EMAIL,
        account_id,
        body.email,
        password_enc_b64,
    )
    return {"queued": True}


@router.post(
    "/{account_id}/2fa/recovery-email/confirm",
    status_code=status.HTTP_202_ACCEPTED,
)
async def confirm_recovery_email(
    account_id: int,
    body: RecoveryEmailConfirm,
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
) -> dict[str, Any]:
    """Подтвердить код, введённый пользователем (этап 7, backlog #1)."""
    _get_account_or_404(session, account_id)
    if not body.code or not body.code.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "code required")
    await task_queue.enqueue(
        TaskName.SECURITY_CONFIRM_RECOVERY_EMAIL,
        account_id,
        body.code.strip(),
    )
    return {"queued": True}


@router.get(
    "/{account_id}/2fa/recovery-email/state",
    response_model=RecoveryEmailState,
)
def get_recovery_email_state(
    account_id: int,
    session: Session = Depends(get_session),
) -> RecoveryEmailState:
    """Текущее состояние привязки recovery-email (читаем meta)."""
    account = _get_account_or_404(session, account_id)
    meta = account.meta or {}
    pending = meta.get("recovery_email_pending") or {}
    return RecoveryEmailState(
        email=meta.get("recovery_email"),
        pending_email=pending.get("email"),
        code_length=pending.get("code_length"),
        confirmed_at=meta.get("recovery_email_confirmed_at"),
    )


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
