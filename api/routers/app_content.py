"""Публичный редактируемый контент приложения.

``GET /app/content`` отдаёт блок «О приложении» и конфиг поддержки (контакт
менеджера, включён ли чат поддержки). Доступно любому авторизованному
пользователю Mini App — редактируется из админки (см. admin-роутер).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from core.content import get_about, get_support

router = APIRouter(prefix="/app", tags=["app-content"])


@router.get("/content")
def app_content(
    _user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    support = get_support(session)
    # Пользователю отдаём только безопасные поля поддержки.
    return {
        "about": get_about(session),
        "support": {
            "manager_username": support.get("manager_username") or "",
            "manager_url": support.get("manager_url") or "",
            "in_app_enabled": bool(support.get("in_app_enabled", True)),
            "intro": support.get("intro") or "",
        },
    }
