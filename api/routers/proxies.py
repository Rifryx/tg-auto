"""Роуты прокси: CRUD + постановка проверки живости в очередь (§6/§10)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.queue import get_task_queue
from core.crypto import encrypt_password
from core.enums import ProxyStatus, ProxyType
from core.queue import TaskQueue
from core.queue.task_names import TaskName
from core.repositories.proxy import ProxyRepository
from core.schemas.proxy import ProxyCreate, ProxyRead, ProxyUpdate


class ProxyCreateRequest(BaseModel):
    """Создание прокси из UI: пароль — плейнтекст, шифруется на сервере.

    login/password опциональны («подписывать» прокси не обязательно)."""

    host: str
    port: int
    type: ProxyType
    login: Optional[str] = None
    password: Optional[str] = None
    geo: Optional[str] = None

router = APIRouter(
    prefix="/proxies", tags=["proxies"], dependencies=[Depends(require_user)]
)


@router.get("", response_model=list[ProxyRead])
def list_proxies(
    status: Optional[ProxyStatus] = None,
    session: Session = Depends(get_session),
) -> list[ProxyRead]:
    repo = ProxyRepository(session)
    proxies = repo.list_by_status(status) if status is not None else repo.list_all()
    return [ProxyRead.model_validate(p) for p in proxies]


@router.get("/{proxy_id}", response_model=ProxyRead)
def get_proxy(proxy_id: int, session: Session = Depends(get_session)) -> ProxyRead:
    proxy = ProxyRepository(session).get(proxy_id)
    if proxy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"proxy {proxy_id} not found")
    return ProxyRead.model_validate(proxy)


@router.post("", response_model=ProxyRead, status_code=status.HTTP_201_CREATED)
def create_proxy(
    body: ProxyCreateRequest, session: Session = Depends(get_session)
) -> ProxyRead:
    pwd_enc = encrypt_password(body.password.encode()) if body.password else None
    create = ProxyCreate(
        host=body.host.strip(),
        port=body.port,
        type=body.type,
        login=(body.login.strip() or None) if body.login else None,
        password_enc=pwd_enc,
        geo=(body.geo.strip() or None) if body.geo else None,
    )
    proxy = ProxyRepository(session).create(create)
    session.commit()
    return ProxyRead.model_validate(proxy)


@router.patch("/{proxy_id}", response_model=ProxyRead)
def patch_proxy(
    proxy_id: int, body: ProxyUpdate, session: Session = Depends(get_session)
) -> ProxyRead:
    proxy = ProxyRepository(session).update(proxy_id, body)
    if proxy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"proxy {proxy_id} not found")
    session.commit()
    return ProxyRead.model_validate(proxy)


@router.delete("/{proxy_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_proxy(proxy_id: int, session: Session = Depends(get_session)) -> None:
    if not ProxyRepository(session).delete(proxy_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"proxy {proxy_id} not found")
    session.commit()


@router.post("/check-all", status_code=status.HTTP_202_ACCEPTED)
async def check_all_proxies(
    task_queue: TaskQueue = Depends(get_task_queue),
) -> dict[str, str]:
    """Ставит проверку живости ВСЕХ прокси (та же задача, что и cron)."""
    job_id = await task_queue.enqueue(TaskName.HEALTH_CHECK_PROXIES)
    return {"job_id": job_id}


@router.post("/{proxy_id}/check", status_code=status.HTTP_202_ACCEPTED)
async def check_proxy(
    proxy_id: int,
    session: Session = Depends(get_session),
    task_queue: TaskQueue = Depends(get_task_queue),
) -> dict[str, str]:
    if ProxyRepository(session).get(proxy_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"proxy {proxy_id} not found")
    job_id = await task_queue.enqueue(TaskName.HEALTH_CHECK_PROXIES, proxy_id)
    return {"job_id": job_id}
