"""Публичный редактируемый контент приложения.

``GET /app/content`` отдаёт блок «О приложении» и конфиг поддержки (контакт
менеджера, включён ли чат поддержки). Доступно любому авторизованному
пользователю Mini App — редактируется из админки (см. admin-роутер).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from typing import Optional

from pydantic import BaseModel, Field, field_validator

from api.deps.auth import require_user
from api.deps.db import get_session
from api.deps.queue import get_publisher
from core.content import (
    get_about,
    get_activity,
    get_plans,
    get_support,
    set_activity,
)
from core.queue.publisher import Publisher
from core.repositories.app_user import AppUserRepository
from core.repositories.support import SupportRepository

router = APIRouter(prefix="/app", tags=["app-content"])

SUPPORT_NEW_MESSAGE_CHANNEL = "support.new_message"


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
        "plans": get_plans(session),
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


# ── Поддержка: чат пользователь↔менеджер внутри приложения ───────────────────


class SupportMessageBody(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def _support_msg_dict(m) -> dict[str, object]:
    return {
        "id": m.id,
        "direction": m.direction,
        "text": m.text,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.get("/support/messages")
def support_thread(
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    support = get_support(session)
    msgs = SupportRepository(session).thread(user_id)
    return {
        "in_app_enabled": bool(support.get("in_app_enabled", True)),
        "messages": [_support_msg_dict(m) for m in msgs],
    }


@router.post("/support/messages")
def support_send(
    body: SupportMessageBody,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
    publisher: Optional[Publisher] = Depends(get_publisher),
) -> dict[str, object]:
    """Пользователь пишет в поддержку. Сообщение сохраняется и best-effort
    публикуется боту, который перешлёт его менеджеру (с @username автора)."""
    # @username автора — чтобы менеджер видел, кто обратился.
    prof = AppUserRepository(session).get_many([user_id]).get(user_id)
    username = prof.username if prof is not None else None

    repo = SupportRepository(session)
    msg = repo.add_message(
        user_id=user_id, direction="user", text=body.text.strip(), username=username
    )
    session.commit()

    # Публикация боту — не критична: если Redis недоступен, сообщение всё равно
    # сохранено и видно пользователю в треде.
    if publisher is not None:
        try:
            publisher.publish(
                SUPPORT_NEW_MESSAGE_CHANNEL,
                {
                    "support_message_id": msg.id,
                    "user_id": user_id,
                    "username": username,
                    "text": msg.text,
                },
            )
        except Exception:  # noqa: BLE001 — доставка боту best-effort
            pass

    return _support_msg_dict(msg)
