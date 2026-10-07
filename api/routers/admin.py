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

from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps.admin import require_admin
from api.deps.db import get_session
from api.services.admin_analytics import get_analytics
from core.audit import admin_action
from core.billing import promotions as promotions_service
from core.billing.plans import PLANS
from core.billing.pricing import get_pricing_config, pricing_snapshot
from core.models.account import Account
from core.models.payment import Payment
from core.models.persona import Persona
from core.models.promotion import Promotion
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


# ----------------------------- аналитика -------------------------------------


@router.get("/analytics")
def analytics(session: Session = Depends(get_session)) -> dict[str, object]:
    """Сводный дашборд: пользователи, выручка, активность, нагрузка."""
    return get_analytics(session)


@router.get("/payments")
def list_payments(
    session: Session = Depends(get_session),
    status_filter: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    stmt = select(Payment).order_by(Payment.created_at.desc())
    if status_filter:
        stmt = stmt.where(Payment.status == status_filter)
    stmt = stmt.limit(max(1, min(limit, 200)))
    rows = session.execute(stmt).scalars()
    return [
        {
            "id": p.id,
            "user_id": p.user_id,
            "provider": p.provider,
            "status": p.status,
            "amount": float(p.amount),
            "currency": p.currency,
            "promo_id": p.promo_id,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "paid_at": p.paid_at.isoformat() if p.paid_at else None,
        }
        for p in rows
    ]


# ----------------------------- цена ------------------------------------------


class PricingBody(BaseModel):
    price_usdt: Decimal = Field(ge=0)
    price_stars: int = Field(ge=0)
    period_days: int = Field(gt=0)


@router.get("/pricing")
def get_pricing(session: Session = Depends(get_session)) -> dict[str, object]:
    cfg = get_pricing_config(session)
    return {
        "price_usdt": float(cfg.price_usdt),
        "price_stars": cfg.price_stars,
        "period_days": cfg.period_days,
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
        "effective": pricing_snapshot(session),
    }


@router.put("/pricing")
def put_pricing(
    body: PricingBody,
    admin_id: str = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    """Обновить базовую цену. Акции считаются поверх — их цены не трогаем."""
    cfg = get_pricing_config(session)
    cfg.price_usdt = body.price_usdt
    cfg.price_stars = body.price_stars
    cfg.period_days = body.period_days
    cfg.updated_by = admin_id
    session.commit()
    admin_action(
        admin_id,
        "set_pricing",
        price_usdt=str(body.price_usdt),
        price_stars=body.price_stars,
        period_days=body.period_days,
    )
    return get_pricing(session)


# ----------------------------- акции -----------------------------------------


class PromotionCreateBody(BaseModel):
    title: str
    description: Optional[str] = None
    kind: Literal["percent", "fixed"]
    percent_off: Optional[int] = None
    promo_price_usdt: Optional[Decimal] = None
    promo_price_stars: Optional[int] = None
    badge_variant: Literal["gold", "fire", "neon"] = "gold"
    starts_at: datetime
    ends_at: datetime
    enabled: bool = True


class PromotionPatchBody(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    kind: Optional[Literal["percent", "fixed"]] = None
    percent_off: Optional[int] = None
    promo_price_usdt: Optional[Decimal] = None
    promo_price_stars: Optional[int] = None
    badge_variant: Optional[Literal["gold", "fire", "neon"]] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    enabled: Optional[bool] = None


def _promo_dict(p: Promotion) -> dict[str, object]:
    return {
        "id": p.id,
        "title": p.title,
        "description": p.description,
        "kind": p.kind,
        "percent_off": p.percent_off,
        "promo_price_usdt": float(p.promo_price_usdt) if p.promo_price_usdt is not None else None,
        "promo_price_stars": p.promo_price_stars,
        "badge_variant": p.badge_variant,
        "starts_at": p.starts_at.isoformat(),
        "ends_at": p.ends_at.isoformat(),
        "enabled": p.enabled,
    }


@router.get("/promotions")
def list_promotions(session: Session = Depends(get_session)) -> list[dict[str, object]]:
    return [_promo_dict(p) for p in promotions_service.list_promotions(session)]


@router.post("/promotions", status_code=status.HTTP_201_CREATED)
def create_promotion(
    body: PromotionCreateBody,
    admin_id: str = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        promo = promotions_service.create_promotion(
            session,
            title=body.title,
            description=body.description,
            kind=body.kind,
            percent_off=body.percent_off,
            promo_price_usdt=body.promo_price_usdt,
            promo_price_stars=body.promo_price_stars,
            badge_variant=body.badge_variant,
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            enabled=body.enabled,
            created_by=admin_id,
        )
    except promotions_service.PromotionValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    admin_action(admin_id, "create_promotion", promo_id=promo.id, title=promo.title)
    return _promo_dict(promo)


@router.patch("/promotions/{promo_id}")
def patch_promotion(
    promo_id: int,
    body: PromotionPatchBody,
    admin_id: str = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    try:
        promo = promotions_service.update_promotion(
            session, promo_id, fields=body.model_dump(exclude_unset=True)
        )
    except promotions_service.PromotionValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if promo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    admin_action(admin_id, "update_promotion", promo_id=promo_id)
    return _promo_dict(promo)


@router.delete("/promotions/{promo_id}")
def delete_promotion(
    promo_id: int,
    admin_id: str = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    if not promotions_service.delete_promotion(session, promo_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    admin_action(admin_id, "delete_promotion", promo_id=promo_id)
    return {"ok": True}
