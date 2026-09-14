"""Роуты аккаунтов: CRUD, прогрев, история, действия (PROJECT-STAGES §6/§10).

Инварианты API-слоя:
* статус НИКОГДА не меняется напрямую — только через :class:`AccountStateMachine`
  (действия retire / acknowledge_ban) либо через очередь (login_start);
* фингерпринт-поля неизменяемы — PATCH их не принимает (schema ``extra=forbid``);
* ответы — read-схемы из ``core``.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.queue import get_publisher, get_task_queue
from api.services import accounts as accounts_service
from core.enums import AccountStatus, Initiator, WarmingProfile
from core.queue import TaskQueue
from core.queue.publisher import Publisher
from core.queue.task_names import TaskName
from core.repositories.account import AccountRepository
from core.repositories.account_status_history import AccountStatusHistoryRepository
from core.repositories.warming_activity import WarmingActivityRepository
from core.schemas.account import AccountRead, AccountUpdate
from core.schemas.history import AccountStatusHistoryRead
from core.schemas.warming import WarmingActivityRead
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
    session: Session = Depends(get_session),
) -> list[AccountRead]:
    accounts = accounts_service.list_accounts(
        session, status=status, warming_profile=warming_profile
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
