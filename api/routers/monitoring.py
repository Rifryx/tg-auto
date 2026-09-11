"""Роут мониторинга: один запрос под экран «Главная» (PROJECT-STAGES §10).

Одной ручкой отдаёт алерты, сводку по стадиям, сводку модулей и ленту
активности. Данные кэшируются в Redis на 5 секунд (ключ по пользователю) —
см. :mod:`api.services.monitoring`.

Монтирование (одной строкой в ``api/main.py``)::

    from api.routers import monitoring
    app.include_router(monitoring.router)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import redis
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from api.services import monitoring as monitoring_service
from api.services.monitoring import get_cache_redis

router = APIRouter(
    prefix="/monitoring", tags=["monitoring"], dependencies=[Depends(require_user)]
)


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
