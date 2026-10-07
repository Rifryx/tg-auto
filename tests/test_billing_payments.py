"""Жизненный цикл платежа: идемпотентность применения, стекание периода,
переиспользование pending, деградация Pro до Free по истечении срока.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from api.services.billing import get_user_plan
from core.billing import payments as payments_service
from core.models.pricing import PricingConfig
from core.models.subscription import Subscription
from core.repositories.subscription import SubscriptionRepository


def _now():
    return datetime.now(timezone.utc)


def _set_period(session, days=30):
    cfg = session.get(PricingConfig, 1)
    cfg.period_days = days
    cfg.price_usdt = Decimal("20.00")
    cfg.price_stars = 1000
    session.flush()


def _expires(session, user_id):
    return SubscriptionRepository(session).get(user_id).expires_at


def test_create_payment_reuses_pending(session):
    _set_period(session)
    p1 = payments_service.create_payment(session, "u-reuse", "crypto")
    p2 = payments_service.create_payment(session, "u-reuse", "crypto")
    assert p1.id == p2.id  # второй клик не создаёт второй инвойс


def test_confirm_is_idempotent(session):
    _set_period(session, 30)
    payment = payments_service.create_payment(session, "u-idem", "crypto")

    r1 = payments_service.confirm_payment(session, payload=payment.payload)
    assert r1.outcome == "applied"
    exp1 = _expires(session, "u-idem")
    assert exp1 is not None

    # Повторная доставка того же платежа — ничего не меняет.
    r2 = payments_service.confirm_payment(session, payload=payment.payload)
    assert r2.outcome == "already_applied"
    exp2 = _expires(session, "u-idem")
    assert exp1 == exp2  # период НЕ добавился второй раз

    assert get_user_plan(session, "u-idem") == "pro"
    # ~30 дней от now.
    assert timedelta(days=29) < (exp1 - _now()) < timedelta(days=31)


def test_two_payments_stack(session):
    _set_period(session, 30)
    p1 = payments_service.create_payment(session, "u-stack", "crypto")
    payments_service.confirm_payment(session, payload=p1.payload)
    exp1 = _expires(session, "u-stack")

    # Первый уже paid → create даёт новый pending.
    p2 = payments_service.create_payment(session, "u-stack", "crypto")
    assert p2.id != p1.id
    payments_service.confirm_payment(session, payload=p2.payload)
    exp2 = _expires(session, "u-stack")

    # Второй период добавился поверх (≈ +30 дней к предыдущему expires).
    assert timedelta(days=29) < (exp2 - exp1) < timedelta(days=31)


def test_confirm_not_found(session):
    r = payments_service.confirm_payment(session, payload="does-not-exist")
    assert r.outcome == "not_found"


def test_pro_expiry_degrades_to_free(session):
    repo = SubscriptionRepository(session)
    # Истёкший Pro → Free.
    sub = Subscription(user_id="u-exp", plan_id="pro", expires_at=_now() - timedelta(days=1))
    session.add(sub)
    session.flush()
    assert get_user_plan(session, "u-exp") == "free"

    # Действующий Pro → Pro.
    sub.expires_at = _now() + timedelta(days=5)
    session.flush()
    assert get_user_plan(session, "u-exp") == "pro"

    # Бессрочный Pro (ручная выдача админом, expires_at=NULL) → Pro.
    sub.expires_at = None
    session.flush()
    assert get_user_plan(session, "u-exp") == "pro"


def test_expire_stale_pending(session):
    _set_period(session)
    payment = payments_service.create_payment(session, "u-stale", "crypto")
    # Утащим срок в прошлое.
    payment.expires_at = _now() - timedelta(minutes=1)
    session.flush()
    n = payments_service.expire_stale_pending(session)
    assert n >= 1
    session.refresh(payment)
    assert payment.status == "expired"
