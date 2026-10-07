"""Жизненный цикл платежа за Pro: создание инвойса → подтверждение → продление.

Здесь живут две самые чувствительные к корректности операции сервиса. Они
спроектированы так, чтобы исключить двойное списание и гонки запросов:

1. ``create_payment`` — создаёт ОДИН pending-платёж. Повторный клик «Оплатить»
   переиспользует живой pending того же (user, provider, plan), а не плодит
   второй инвойс. ``payload`` уникален на уровне БД.

2. ``confirm_payment`` — применяет оплату РОВНО ОДИН РАЗ. Внутри одной
   транзакции: ``SELECT … FOR UPDATE`` строки платежа → если уже ``paid``, это
   no-op (идемпотентность) → иначе помечаем ``paid`` и в той же транзакции
   продлеваем подписку атомарным upsert'ом. Любые повторы (ретраи Telegram и
   CryptoBot, одновременные cron-сверка и on-demand-проверка) не продлят
   подписку дважды: блокировка строки сериализует их, а проверка статуса
   обрывает второй проход.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from core.billing.pricing import get_effective_pricing
from core.config import get_settings
from core.models.payment import Payment
from core.repositories.subscription import SubscriptionRepository

Provider = Literal["stars", "crypto"]

_DEFAULT_TTL = timedelta(minutes=15)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ConfirmResult:
    outcome: Literal["applied", "already_applied", "not_found", "not_paid"]
    payment: Optional[Payment] = None


def _reuse_pending(
    session: Session, user_id: str, provider: str, plan_id: str
) -> Optional[Payment]:
    stmt = (
        select(Payment)
        .where(
            Payment.user_id == user_id,
            Payment.provider == provider,
            Payment.plan_id == plan_id,
            Payment.status == "pending",
            Payment.expires_at > _now(),
        )
        .order_by(Payment.created_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalars().first()


def create_payment(
    session: Session,
    user_id: str,
    provider: Provider,
    plan_id: str = "pro",
    ttl: timedelta = _DEFAULT_TTL,
) -> Payment:
    """Создать (или переиспользовать) pending-платёж с зафиксированной ценой.

    Коммитит сессию: платёж должен быть виден другим процессам (боту, cron)
    ещё до того, как провайдер вернёт инвойс/оплату.
    """
    existing = _reuse_pending(session, user_id, provider, plan_id)
    if existing is not None:
        return existing

    eff = get_effective_pricing(session)
    settings = get_settings()

    if provider == "crypto":
        amount: Decimal = eff.price_usdt
        currency = settings.cryptobot_asset
    else:  # stars
        amount = Decimal(eff.price_stars)
        currency = "XTR"

    payment = Payment(
        user_id=user_id,
        provider=provider,
        payload=secrets.token_urlsafe(24),
        status="pending",
        amount=amount,
        currency=currency,
        plan_id=plan_id,
        period_days=eff.period_days,
        promo_id=eff.promo.id if eff.promo else None,
        price_usdt=eff.price_usdt,
        price_stars=eff.price_stars,
        expires_at=_now() + ttl,
    )
    session.add(payment)
    session.commit()
    session.refresh(payment)
    return payment


def _lock_payment(
    session: Session,
    *,
    payload: Optional[str] = None,
    provider: Optional[str] = None,
    provider_invoice_id: Optional[str] = None,
) -> Optional[Payment]:
    """Найти и заблокировать (FOR UPDATE) строку платежа для применения."""
    stmt = select(Payment)
    if payload is not None:
        stmt = stmt.where(Payment.payload == payload)
    elif provider is not None and provider_invoice_id is not None:
        stmt = stmt.where(
            Payment.provider == provider,
            Payment.provider_invoice_id == provider_invoice_id,
        )
    else:
        raise ValueError("confirm_payment requires payload or (provider, invoice_id)")
    return session.execute(stmt.with_for_update()).scalars().first()


def confirm_payment(
    session: Session,
    *,
    payload: Optional[str] = None,
    provider: Optional[str] = None,
    provider_invoice_id: Optional[str] = None,
    set_invoice_id: Optional[str] = None,
) -> ConfirmResult:
    """Идемпотентно подтвердить оплату и продлить подписку.

    Критическая секция целиком под блокировкой строки платежа; коммит
    закрывает транзакцию (и снимает блокировку) одним актом вместе с
    продлением подписки.

    :param set_invoice_id: id инвойса провайдера, который нужно записать при
        подтверждении (для Stars — ``telegram_payment_charge_id``, приходящий
        только в ``successful_payment``).
    """
    payment = _lock_payment(
        session,
        payload=payload,
        provider=provider,
        provider_invoice_id=provider_invoice_id,
    )
    if payment is None:
        session.rollback()
        return ConfirmResult(outcome="not_found")

    if payment.status == "paid" and payment.applied_at is not None:
        # Уже применён — ничего не делаем. Это и есть идемпотентность.
        session.rollback()
        return ConfirmResult(outcome="already_applied", payment=payment)

    now = _now()
    if set_invoice_id is not None and payment.provider_invoice_id is None:
        payment.provider_invoice_id = set_invoice_id
    payment.status = "paid"
    payment.paid_at = payment.paid_at or now
    payment.applied_at = now

    SubscriptionRepository(session).extend_pro(
        payment.user_id, payment.period_days, payment_method=payment.provider
    )
    session.commit()
    session.refresh(payment)
    return ConfirmResult(outcome="applied", payment=payment)


def expire_stale_pending(session: Session) -> int:
    """Пометить просроченные pending-платежи как ``expired``. Возвращает число."""
    result = session.execute(
        update(Payment)
        .where(Payment.status == "pending", Payment.expires_at <= _now())
        .values(status="expired")
    )
    session.commit()
    return int(result.rowcount or 0)
