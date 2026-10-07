"""Эффективная цена подписки = базовая цена + активная акция «сейчас».

Единственный источник правды по цене. Базу держит ``pricing_config`` (одна
строка), акции — ``promotions``. Ключевой инвариант MVP:

    Промо-цена НИКОГДА не записывается в базовую. Эффективная цена всегда
    пересчитывается на лету из (база, активная-акция-на-момент-now). Как только
    окно акции закрылось — цена автоматически возвращается к базовой.

Поэтому «залипнуть» на акционной цене после её окончания невозможно: нет поля,
где акционная цена могла бы сохраниться как базовая.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models.payment import Payment  # noqa: F401  (удобство импорта для сервисов)
from core.models.pricing import PRICING_SINGLETON_ID, PricingConfig
from core.models.promotion import Promotion

_CENTS = Decimal("0.01")


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class PromoView:
    id: int
    title: str
    description: Optional[str]
    badge_variant: str
    kind: str
    ends_at: datetime


@dataclass(frozen=True)
class EffectivePricing:
    """Итоговая цена, которую видит пользователь и которую фиксирует инвойс."""

    price_usdt: Decimal
    price_stars: int
    period_days: int
    base_price_usdt: Decimal
    base_price_stars: int
    promo: Optional[PromoView]


def get_pricing_config(session: Session) -> PricingConfig:
    """Singleton-строка конфигурации цены. Должна существовать (сид в 0054)."""
    cfg = session.get(PricingConfig, PRICING_SINGLETON_ID)
    if cfg is None:  # оборонительно: окружение без сид-строки
        raise RuntimeError("pricing_config singleton row is missing (run migrations)")
    return cfg


def get_active_promo(session: Session, now: Optional[datetime] = None) -> Optional[Promotion]:
    """Акция, действующая прямо сейчас: enabled и now ∈ [starts_at, ends_at).

    Если по недосмотру активны несколько — берём начавшуюся позже (детерминизм).
    На запись валидатор не даёт создавать пересекающиеся активные окна.
    """
    now = now or _now()
    stmt = (
        select(Promotion)
        .where(
            Promotion.enabled.is_(True),
            Promotion.starts_at <= now,
            Promotion.ends_at > now,
        )
        .order_by(Promotion.starts_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalars().first()


def _apply_promo_usdt(base: Decimal, promo: Promotion) -> Decimal:
    if promo.kind == "fixed" and promo.promo_price_usdt is not None:
        price = Decimal(promo.promo_price_usdt)
    else:  # percent
        factor = (Decimal(100) - Decimal(promo.percent_off or 0)) / Decimal(100)
        price = Decimal(base) * factor
    price = price.quantize(_CENTS, rounding=ROUND_HALF_UP)
    return max(price, Decimal("0.00"))


def _apply_promo_stars(base: int, promo: Promotion) -> int:
    if promo.kind == "fixed" and promo.promo_price_stars is not None:
        price = int(promo.promo_price_stars)
    else:  # percent
        price = int(round(base * (100 - (promo.percent_off or 0)) / 100))
    return max(price, 0)


def compute_effective(cfg: PricingConfig, promo: Optional[Promotion]) -> EffectivePricing:
    """Чистая функция расчёта (без БД) — удобно юнит-тестировать."""
    base_usdt = Decimal(cfg.price_usdt).quantize(_CENTS)
    base_stars = int(cfg.price_stars)
    if promo is None:
        return EffectivePricing(
            price_usdt=base_usdt,
            price_stars=base_stars,
            period_days=int(cfg.period_days),
            base_price_usdt=base_usdt,
            base_price_stars=base_stars,
            promo=None,
        )
    return EffectivePricing(
        price_usdt=_apply_promo_usdt(base_usdt, promo),
        price_stars=_apply_promo_stars(base_stars, promo),
        period_days=int(cfg.period_days),
        base_price_usdt=base_usdt,
        base_price_stars=base_stars,
        promo=PromoView(
            id=promo.id,
            title=promo.title,
            description=promo.description,
            badge_variant=promo.badge_variant,
            kind=promo.kind,
            ends_at=promo.ends_at,
        ),
    )


def get_effective_pricing(
    session: Session, now: Optional[datetime] = None
) -> EffectivePricing:
    cfg = get_pricing_config(session)
    promo = get_active_promo(session, now)
    return compute_effective(cfg, promo)


def pricing_snapshot(session: Session, now: Optional[datetime] = None) -> dict[str, object]:
    """Словарь для JSON-ответов (``GET /billing/plan`` и т.п.)."""
    eff = get_effective_pricing(session, now)
    promo = (
        {
            "id": eff.promo.id,
            "title": eff.promo.title,
            "description": eff.promo.description,
            "badge_variant": eff.promo.badge_variant,
            "kind": eff.promo.kind,
            "ends_at": eff.promo.ends_at.isoformat(),
        }
        if eff.promo
        else None
    )
    return {
        "price_usdt": float(eff.price_usdt),
        "price_stars": eff.price_stars,
        "period_days": eff.period_days,
        "base_price_usdt": float(eff.base_price_usdt),
        "base_price_stars": eff.base_price_stars,
        "has_promo": eff.promo is not None,
        "promo": promo,
    }
