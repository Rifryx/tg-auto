"""Акция на подписку Pro — временно́е окно скидки поверх базовой цены.

Акция НЕ меняет :class:`core.models.pricing.PricingConfig`; она описывает, как
пересчитать цену, пока ``enabled`` и ``now ∈ [starts_at, ends_at)``. Как только
окно закрылось — эффективная цена автоматически возвращается к базовой (расчёт
в ``core.billing.pricing``). Это и есть гарантия «после акции цена не залипает».

Два вида (``kind``):
* ``percent`` — скидка ``percent_off`` процентов от базовой цены обеих валют.
* ``fixed``   — явные промо-цены ``promo_price_usdt`` и ``promo_price_stars``.

``badge_variant`` задаёт характерный дизайн PRO-иконки и «шторки» на фронте.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, TimestampMixin

# Допустимые визуальные варианты бейджа/шторки. Фронт мапит их в стили.
PROMO_BADGE_VARIANTS = ("gold", "fire", "neon")


class Promotion(Base, TimestampMixin):
    __tablename__ = "promotions"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('percent', 'fixed')", name="kind_allowed"
        ),
        # percent: нужен корректный percent_off; fixed: нужны обе промо-цены.
        CheckConstraint(
            "(kind = 'percent' AND percent_off IS NOT NULL "
            "AND percent_off BETWEEN 1 AND 95) "
            "OR (kind = 'fixed' AND promo_price_usdt IS NOT NULL "
            "AND promo_price_stars IS NOT NULL)",
            name="kind_fields_consistent",
        ),
        CheckConstraint("ends_at > starts_at", name="window_valid"),
        Index("ix_promotions_window", "enabled", "starts_at", "ends_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    kind: Mapped[str] = mapped_column(String, nullable=False)
    percent_off: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    promo_price_usdt: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    promo_price_stars: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    badge_variant: Mapped[str] = mapped_column(
        String, nullable=False, default="gold", server_default="gold"
    )

    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ends_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
