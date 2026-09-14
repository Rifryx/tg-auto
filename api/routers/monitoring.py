"""Роут мониторинга: один запрос под экран «Главная» (PROJECT-STAGES §10).

Одной ручкой отдаёт алерты, сводку по стадиям, сводку модулей и ленту
активности. Данные кэшируются в Redis на 5 секунд (ключ по пользователю) —
см. :mod:`api.services.monitoring`.

Монтирование (одной строкой в ``api/main.py``)::

    from api.routers import monitoring
    app.include_router(monitoring.router)
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Optional

import redis
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from api.services import monitoring as monitoring_service
from api.services.events import MonitoringEventHub, get_monitoring_hub
from api.services.monitoring import get_cache_redis

router = APIRouter(
    prefix="/monitoring", tags=["monitoring"], dependencies=[Depends(require_user)]
)

_SSE_KEEPALIVE_SECONDS = 15.0


class AlertItem(BaseModel):
    id: int
    account_id: int
    phone: Optional[str] = None
    event_type: str
    severity: str
    created_at: Optional[datetime] = None
    meta: Optional[dict[str, Any]] = None


class AccountsSummary(BaseModel):
    created: int
    warming: int
    pool: int
    assigned: int
    cooldown: int
    retired: int
    banned: int


class ModuleSummary(BaseModel):
    module: str
    instances: int
    active_now: int
    today_actions: int


class ActivityItem(BaseModel):
    type: str
    account_id: int
    summary: str
    timestamp: Optional[datetime] = None


class DashboardResponse(BaseModel):
    alerts: list[AlertItem]
    accounts_summary: AccountsSummary
    modules_summary: list[ModuleSummary]
    recent_activity: list[ActivityItem]


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(
    severity: Optional[str] = None,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
    cache: redis.Redis = Depends(get_cache_redis),
) -> dict[str, Any]:
    return monitoring_service.get_dashboard(session, cache, user_id, severity)


@router.get("/stream")
async def monitoring_stream(
    request: Request,
    hub: MonitoringEventHub = Depends(get_monitoring_hub),
) -> StreamingResponse:
    """Живой поток доменных событий (account_status/health_alert/warming_progress)
    для мгновенного обновления дашборда без ожидания refetch (аудит #9)."""
    await hub.ensure_started()
    queue = hub.subscribe()

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
                yield f"data: {json.dumps(entry, default=str)}\n\n"
        finally:
            hub.unsubscribe(queue)

    return StreamingResponse(event_source(), media_type="text/event-stream")
