"""Расчёт эффективной цены: скидки percent/fixed и — главное — автоматический
откат к базовой цене после окончания окна акции.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from core.billing.pricing import (
    compute_effective,
    get_active_promo,
    get_effective_pricing,
)
from core.models.pricing import PricingConfig
from core.models.promotion import Promotion


def _cfg(usdt="20.00", stars=1000, period=30) -> PricingConfig:
    return PricingConfig(
        id=1, price_usdt=Decimal(usdt), price_stars=stars, period_days=period
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- чистый расчёт (без БД) ---------------------------------------------------


def test_no_promo_returns_base():
    eff = compute_effective(_cfg(), None)
    assert eff.price_usdt == Decimal("20.00")
    assert eff.price_stars == 1000
    assert eff.promo is None


def test_percent_discount():
    promo = Promotion(
        title="−25%", kind="percent", percent_off=25,
        badge_variant="gold", starts_at=_now(), ends_at=_now() + timedelta(days=1),
        enabled=True,
    )
    eff = compute_effective(_cfg("20.00", 1000), promo)
    assert eff.price_usdt == Decimal("15.00")
    assert eff.price_stars == 750
    assert eff.base_price_usdt == Decimal("20.00")
    assert eff.promo is not None and eff.promo.kind == "percent"


def test_fixed_price_override():
    promo = Promotion(
        title="Fixed", kind="fixed", promo_price_usdt=Decimal("9.99"),
        promo_price_stars=500, badge_variant="fire",
        starts_at=_now(), ends_at=_now() + timedelta(days=1), enabled=True,
    )
    eff = compute_effective(_cfg("20.00", 1000), promo)
    assert eff.price_usdt == Decimal("9.99")
    assert eff.price_stars == 500


# --- оконная логика и откат (БД) ---------------------------------------------


def _seed_base(session, usdt="20.00", stars=1000, period=30):
    cfg = session.get(PricingConfig, 1)
    cfg.price_usdt = Decimal(usdt)
    cfg.price_stars = stars
    cfg.period_days = period
    session.flush()


def test_active_promo_applies_then_reverts(session):
    _seed_base(session)
    now = _now()
    # Акция уже закончилась час назад.
    past = Promotion(
        title="старая", kind="percent", percent_off=50, badge_variant="gold",
        starts_at=now - timedelta(days=2), ends_at=now - timedelta(hours=1),
        enabled=True,
    )
    session.add(past)
    session.flush()
    # Прошедшая акция не активна -> цена базовая.
    assert get_active_promo(session, now) is None
    assert get_effective_pricing(session, now).price_usdt == Decimal("20.00")

    # Активная сейчас акция -> цена со скидкой.
    live = Promotion(
        title="сейчас", kind="percent", percent_off=50, badge_variant="fire",
        starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=1),
        enabled=True,
    )
    session.add(live)
    session.flush()
    eff = get_effective_pricing(session, now)
    assert eff.price_usdt == Decimal("10.00")
    assert eff.promo is not None and eff.promo.title == "сейчас"

    # Момент времени ПОСЛЕ конца окна -> снова базовая, автоматически.
    after = now + timedelta(hours=2)
    assert get_active_promo(session, after) is None
    assert get_effective_pricing(session, after).price_usdt == Decimal("20.00")


def test_disabled_promo_ignored(session):
    _seed_base(session)
    now = _now()
    promo = Promotion(
        title="выкл", kind="percent", percent_off=90, badge_variant="neon",
        starts_at=now - timedelta(hours=1), ends_at=now + timedelta(hours=1),
        enabled=False,
    )
    session.add(promo)
    session.flush()
    assert get_active_promo(session, now) is None
    assert get_effective_pricing(session, now).price_usdt == Decimal("20.00")
