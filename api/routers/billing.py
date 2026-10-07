"""Роутер тарифа и оплаты подписки Pro.

* ``GET  /billing/plan``                 — план, лимиты, использование, цены, срок.
* ``POST /billing/invoice``              — создать инвойс (Stars / Crypto Bot).
* ``POST /billing/payments/{id}/check``  — on-demand сверка крипто-оплаты.
* ``GET  /billing/promo``                — активная акция (если не скрыта юзером).
* ``POST /billing/promo/{id}/dismiss``   — скрыть шторку акции.
* ``POST /billing/plan``                 — прямое переключение, ТОЛЬКО в DEV_MODE
  (в проде оплата идёт через инвойс+подтверждение провайдера).

Идентичность пользователя — всегда из подписанного initData (``require_user``),
никогда из тела запроса.
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps.auth import require_user
from api.deps.db import get_session
from api.services import billing as billing_service
from core.billing import payments as payments_service
from core.billing import promotions as promotions_service
from core.billing.providers import cryptobot, stars
from core.config import get_settings

router = APIRouter(prefix="/billing", tags=["billing"])


class SetPlanRequest(BaseModel):
    plan_id: Literal["free", "pro"]
    payment_method: Optional[Literal["stars", "crypto"]] = None


class InvoiceRequest(BaseModel):
    plan_id: Literal["pro"] = "pro"
    provider: Literal["stars", "crypto"]


@router.get("/plan")
def get_plan(
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return billing_service.get_usage_snapshot(session, user_id)


@router.post("/invoice")
def create_invoice(
    body: InvoiceRequest,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    """Создать (или переиспользовать) инвойс на Pro и вернуть ссылку оплаты."""
    payment = payments_service.create_payment(
        session, user_id, body.provider, body.plan_id
    )
    # Если ссылка уже получена ранее (переиспользуемый pending) — отдаём её.
    if payment.pay_url:
        return _invoice_response(payment)

    description = f"Pro подписка на {payment.period_days} дн."
    if body.provider == "crypto":
        inv = cryptobot.create_invoice(
            amount=f"{payment.price_usdt}",
            payload=payment.payload,
            description=description,
        )
        payment.provider_invoice_id = inv.invoice_id
        payment.pay_url = inv.pay_url
    else:  # stars
        payment.pay_url = stars.create_invoice_link(
            title="Pro подписка",
            description=description,
            payload=payment.payload,
            stars=payment.price_stars,
        )
    session.commit()
    session.refresh(payment)
    return _invoice_response(payment)


def _invoice_response(payment) -> dict[str, object]:
    return {
        "payment_id": payment.id,
        "provider": payment.provider,
        "url": payment.pay_url,
        "amount": float(payment.amount),
        "currency": payment.currency,
        "status": payment.status,
    }


@router.post("/payments/{payment_id}/check")
def check_payment(
    payment_id: int,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    """Проверить и, если оплачено, применить платёж (идемпотентно).

    Для Crypto Bot опрашиваем статус инвойса; для Stars статус приходит через
    бота — здесь лишь возвращаем текущее состояние.
    """
    from core.models.payment import Payment

    payment = session.get(Payment, payment_id)
    if payment is None or payment.user_id != user_id:
        # Чужой/несуществующий платёж не подтверждаем и не раскрываем.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    if payment.status == "paid":
        return {"status": "paid", "plan": billing_service.get_user_plan(session, user_id)}

    if payment.provider == "crypto":
        paid = cryptobot.get_paid_invoice_ids([payment.provider_invoice_id or ""])
        if payment.provider_invoice_id and payment.provider_invoice_id in paid:
            payments_service.confirm_payment(session, payload=payment.payload)

    # Перечитываем актуальный статус (confirm_payment коммитит в своей сессии).
    session.expire_all()
    payment = session.get(Payment, payment_id)
    return {
        "status": payment.status,
        "plan": billing_service.get_user_plan(session, user_id),
    }


@router.get("/promo")
def get_promo(
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    """Активная акция для шторки (None, если нет или уже скрыта пользователем)."""
    promo = promotions_service.get_promo_for_user(session, user_id)
    if promo is None:
        return {"promo": None}
    return {
        "promo": {
            "id": promo.id,
            "title": promo.title,
            "description": promo.description,
            "badge_variant": promo.badge_variant,
            "ends_at": promo.ends_at.isoformat(),
        }
    }


@router.post("/promo/{promo_id}/dismiss")
def dismiss_promo(
    promo_id: int,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    promotions_service.dismiss_promo(session, user_id, promo_id)
    return {"ok": True}


@router.post("/plan")
def set_plan(
    body: SetPlanRequest,
    user_id: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    """Прямое переключение плана — ТОЛЬКО в DEV_MODE (локальная проверка/тесты).

    В проде этот путь закрыт (404): активация идёт исключительно через оплату и
    подтверждение провайдера, иначе остался бы обход оплаты.
    """
    if not get_settings().dev_mode:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    billing_service.set_user_plan(session, user_id, body.plan_id, body.payment_method)
    return billing_service.get_usage_snapshot(session, user_id)
