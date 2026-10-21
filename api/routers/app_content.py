"""Публичный редактируемый контент приложения.

``GET /app/content`` отдаёт блок «О приложении» и конфиг поддержки (контакт
менеджера, включён ли чат поддержки). Доступно любому авторизованному
пользователю Mini App — редактируется из админки (см. admin-роутер).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from pydantic import BaseModel, Field, field_validator

from api.deps.auth import require_user
from api.deps.db import get_session
from core.content import get_about, get_activity, get_support, set_activity

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
        "activity": get_activity(session),
        "support": {
            "manager_username": support.get("manager_username") or "",
            "manager_url": support.get("manager_url") or "",
            "in_app_enabled": bool(support.get("in_app_enabled", True)),
            "intro": support.get("intro") or "",
        },
    }


_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class ActivityBody(BaseModel):
    timezone: str = Field(min_length=1, max_length=64)
    window_start: str = Field(pattern=_HHMM)
    window_end: str = Field(pattern=_HHMM)

    @field_validator("timezone")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(v)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"unknown timezone: {v}") from exc
        return v


@router.put("/settings/activity")
def put_activity(
    body: ActivityBody,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    """Сохранить таймзону и окно активности (учитываются прогревом и в UI)."""
    activity = set_activity(session, body.model_dump(), updated_by=user_id)
    session.commit()
    return activity
