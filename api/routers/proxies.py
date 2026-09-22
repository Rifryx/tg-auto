"""Роуты прокси: CRUD + постановка проверки живости в очередь + автопик (§6/§10)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.limits import enforce_limit
from api.deps.queue import get_task_queue
from core.crypto import encrypt_password
from core.enums import ProxyStatus, ProxyType
from core.models import Account
from core.queue import TaskQueue
from core.queue.task_names import TaskName
from core.repositories.proxy import ProxyRepository
from core.repositories.proxy_pool import detect_geo, pick_for_phone, pick_free_proxy
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


class ProxyOccupancy(BaseModel):
    """Расширенный view прокси: занят ли и каким аккаунтом (этап 3, backlog #2)."""

    id: int
    host: str
    port: int
    type: ProxyType
    geo: Optional[str]
    status: ProxyStatus
    last_checked_at: Optional[str]
    assigned_account_id: Optional[int]
    is_free: bool


@router.get("", response_model=list[ProxyRead])
def list_proxies(
    status: Optional[ProxyStatus] = None,
    session: Session = Depends(get_session),
) -> list[ProxyRead]:
    repo = ProxyRepository(session)
    proxies = repo.list_by_status(status) if status is not None else repo.list_all()
    return [ProxyRead.model_validate(p) for p in proxies]


@router.get("/pool", response_model=list[ProxyOccupancy])
def list_pool(
    session: Session = Depends(get_session),
) -> list[ProxyOccupancy]:
    """Все прокси с флагом занятости — для UI пула прокси (этап 3)."""
    proxies = ProxyRepository(session).list_all()
    # Один SELECT на карту proxy_id → account_id, чтобы не делать N+1.
    occupancy_rows = session.execute(
        select(Account.proxy_id, Account.id).where(Account.proxy_id.is_not(None))
    ).all()
    occupancy: dict[int, int] = {pid: aid for pid, aid in occupancy_rows}
    return [
        ProxyOccupancy(
            id=p.id, host=p.host, port=p.port, type=p.type, geo=p.geo,
            status=p.status,
            last_checked_at=p.last_checked_at.isoformat() if p.last_checked_at else None,
            assigned_account_id=occupancy.get(p.id),
            is_free=p.id not in occupancy,
        )
        for p in proxies
    ]


class ProxyPickResponse(BaseModel):
    proxy_id: Optional[int] = None
    detected_geo: Optional[str] = None
    reason: Optional[str] = None


@router.get("/pick", response_model=ProxyPickResponse)
def pick_proxy(
    phone: Optional[str] = None,
    geo: Optional[str] = None,
    strict_geo: bool = True,
    session: Session = Depends(get_session),
) -> ProxyPickResponse:
    """Автопик свободного alive-прокси под номер/гео (этап 3, backlog #1).

    Приоритет параметров: явно указанный ``geo`` перекрывает автоопределение
    по ``phone``. ``strict_geo=False`` разрешает подобрать прокси другой
    страны, если matching-гео пусто (админский override — по умолчанию
    выключено, инвариант §0.4).
    """
    target_geo = (geo or "").strip().upper() or None
    detected = None
    if phone and not target_geo:
        detected = detect_geo(phone)
        target_geo = detected

    if phone:
        chosen = pick_for_phone(session, phone, strict_geo=strict_geo)
    else:
        chosen = pick_free_proxy(session, geo=target_geo, strict_geo=strict_geo)

    if chosen is None:
        return ProxyPickResponse(
            detected_geo=detected,
            reason=(
                "no_matching_geo_proxy" if target_geo
                else "no_free_proxy"
            ),
        )
    return ProxyPickResponse(proxy_id=chosen.id, detected_geo=detected)


@router.get("/{proxy_id}", response_model=ProxyRead)
def get_proxy(proxy_id: int, session: Session = Depends(get_session)) -> ProxyRead:
    proxy = ProxyRepository(session).get(proxy_id)
    if proxy is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"proxy {proxy_id} not found")
    return ProxyRead.model_validate(proxy)


@router.post("", response_model=ProxyRead, status_code=status.HTTP_201_CREATED)
def create_proxy(
    body: ProxyCreateRequest,
    session: Session = Depends(get_session),
    _limit: None = Depends(enforce_limit("proxies_max")),
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
