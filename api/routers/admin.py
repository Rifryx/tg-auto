"""Админ-роутер.

Все эндпоинты защищены ``require_admin``. Не-админ получает 404 и не может
отличить админку от несуществующего пути.

Что доступно:
* ``GET  /admin/me``            — эхо: подтверждение, что запрос админский.
* ``GET  /admin/stats``         — сводные счётчики.
* ``GET  /admin/subscriptions`` — список подписок.
* ``POST /admin/subscriptions/{user_id}`` — сменить план пользователя вручную.

Никакой user_id ниже НЕ читается из тела/URL, кроме случая, когда админ явно
управляет чужой подпиской — тогда это параметр операции, а не идентификатор
инициатора.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps.admin import require_admin
from api.deps.db import get_session
from core.audit import admin_action
from core.billing.plans import PLANS
from core.models.account import Account
from core.models.persona import Persona
from core.models.proxy import Proxy
from core.models.subscription import Subscription
from core.repositories.subscription import SubscriptionRepository
from modules.commenting.models.campaign import Campaign

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


class SetPlanBody(BaseModel):
    plan_id: Literal["free", "pro"]
    reason: str | None = None


@router.get("/me")
def me(admin_id: str = Depends(require_admin)) -> dict[str, object]:
    return {"user_id": admin_id, "is_admin": True}


@router.get("/stats")
def stats(session: Session = Depends(get_session)) -> dict[str, int]:
    def _count(model) -> int:
        return int(session.execute(select(func.count()).select_from(model)).scalar_one())

    return {
        "users": _count(Subscription),
        "accounts": _count(Account),
        "personas": _count(Persona),
        "proxies": _count(Proxy),
        "campaigns": _count(Campaign),
        "pro_users": int(
            session.execute(
                select(func.count()).select_from(Subscription).where(
                    Subscription.plan_id == "pro"
                )
            ).scalar_one()
        ),
    }


@router.get("/subscriptions")
def list_subscriptions(
    session: Session = Depends(get_session),
) -> list[dict[str, object]]:
    rows = session.execute(select(Subscription).order_by(Subscription.updated_at.desc())).scalars()
    return [
        {
            "user_id": s.user_id,
            "plan_id": s.plan_id,
            "activated_at": s.activated_at.isoformat() if s.activated_at else None,
            "expires_at": s.expires_at.isoformat() if s.expires_at else None,
            "payment_method": s.payment_method,
        }
        for s in rows
    ]


@router.post("/subscriptions/{target_user_id}", status_code=status.HTTP_200_OK)
def set_subscription(
    target_user_id: str,
    body: SetPlanBody,
    admin_id: str = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    if body.plan_id not in PLANS:
        # Мы уже валидируем через Literal, но оставляем защиту от подмены enum.
        return {"ok": False, "error": "unknown plan"}
    SubscriptionRepository(session).upsert(target_user_id, body.plan_id)
    session.commit()
    admin_action(
        admin_id,
        "set_subscription",
        target=target_user_id,
        plan=body.plan_id,
        reason=body.reason,
    )
    return {"ok": True, "user_id": target_user_id, "plan_id": body.plan_id}
