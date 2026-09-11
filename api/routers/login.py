"""Роуты оркестрации логина (PROJECT-STAGES §11).

API только ставит команды в очередь и отдаёт состояние логина, которое приходит
обратно через Redis pub/sub. НИКАКИХ вызовов Telethon в API-процессе.

Монтирование в приложение (одной строкой в ``api/main.py``)::

    from api.routers import login
    app.include_router(login.router)
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.queue import get_task_queue
from api.services.login import LoginEventHub, get_login_hub
from core.queue import TaskQueue
from core.queue.task_names import TaskName
from core.repositories.account import AccountRepository

router = APIRouter(
    prefix="/accounts", tags=["login"], dependencies=[Depends(require_user)]
)

_SSE_KEEPALIVE_SECONDS = 15.0


class CodeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str


class PasswordBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str


class LoginStateResponse(BaseModel):
    account_id: int
    state: Optional[str] = None
    reason: Optional[str] = None
    updated_at: Optional[datetime] = None


def _require_account(session: Session, account_id: int) -> None:
    if AccountRepository(session).get(account_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"account {account_id} not found")


def _current_state(
    hub: LoginEventHub, session: Session, account_id: int
) -> LoginStateResponse:
    entry = hub.get_state(account_id)
    if entry is not None:
        return LoginStateResponse(**entry)
    # Кэш пуст — деривация из meta: наличие phone_code_hash значит «ждём код».
    account = AccountRepository(session).get(account_id)
    meta = (account.meta or {}) if account is not None else {}
    state = "waiting_code" if meta.get("phone_code_hash") else None
    return LoginStateResponse(account_id=account_id, state=state)


def _sse(entry: dict) -> str:
    payload = {
        "account_id": entry.get("account_id"),
        "state": entry.get("state"),
        "reason": entry.get("reason"),
        "updated_at": entry.get("updated_at"),
    }
    return f"data: {json.dumps(payload, default=str)}\n\n"


@router.post("/{account_id}/login/start", response_model=LoginStateResponse)
async def login_start(
    account_id: int,
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
    hub: LoginEventHub = Depends(get_login_hub),
) -> LoginStateResponse:
    _require_account(session, account_id)
    await task_queue.enqueue(TaskName.ACCOUNT_LOGIN_START, account_id)
    return _current_state(hub, session, account_id)


@router.post("/{account_id}/login/confirm", response_model=LoginStateResponse)
async def login_confirm(
    account_id: int,
    body: CodeBody,
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
    hub: LoginEventHub = Depends(get_login_hub),
) -> LoginStateResponse:
    _require_account(session, account_id)
    await task_queue.enqueue(TaskName.ACCOUNT_LOGIN_CONFIRM, account_id, body.code)
    return _current_state(hub, session, account_id)


@router.post("/{account_id}/login/password", response_model=LoginStateResponse)
async def login_password(
    account_id: int,
    body: PasswordBody,
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
    hub: LoginEventHub = Depends(get_login_hub),
) -> LoginStateResponse:
    _require_account(session, account_id)
    await task_queue.enqueue(TaskName.ACCOUNT_LOGIN_PASSWORD, account_id, body.password)
    return _current_state(hub, session, account_id)


@router.get("/{account_id}/login/state", response_model=LoginStateResponse)
def login_state(
    account_id: int,
    session: Session = Depends(get_session),
    hub: LoginEventHub = Depends(get_login_hub),
) -> LoginStateResponse:
    _require_account(session, account_id)
    return _current_state(hub, session, account_id)


@router.get("/{account_id}/login/stream")
async def login_stream(
    account_id: int,
    request: Request,
    session: Session = Depends(get_session),
    hub: LoginEventHub = Depends(get_login_hub),
) -> StreamingResponse:
    _require_account(session, account_id)
    await hub.ensure_started()
    queue = hub.subscribe(account_id)

    async def event_source():
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    entry = await asyncio.wait_for(
                        queue.get(), timeout=_SSE_KEEPALIVE_SECONDS
                    )
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield _sse(entry)
        finally:
            hub.unsubscribe(account_id, queue)

    return StreamingResponse(event_source(), media_type="text/event-stream")
