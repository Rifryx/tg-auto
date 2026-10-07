"""Конфигурация цены подписки Pro — единственная строка (singleton).

Базовая цена в USDT и в Telegram Stars хранится раздельно (разные валюты, не
конвертируем на лету), плюс длительность периода подписки в днях. Акции
(:class:`core.models.promotion.Promotion`) накладываются поверх этой базы и
НЕ перезаписывают её — см. ``core.billing.pricing.get_effective_pricing``.

Инвариант singleton: всегда ровно одна строка с ``id == 1``. Миграция 0054
сидит её значениями по умолчанию; сервис читает/обновляет именно её.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, Integer, Numeric, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base

PRICING_SINGLETON_ID = 1


class PricingConfig(Base):
    __tablename__ = "pricing_config"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint("price_usdt >= 0", name="price_usdt_nonneg"),
        CheckConstraint("price_stars >= 0", name="price_stars_nonneg"),
        CheckConstraint("period_days > 0", name="period_days_positive"),
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    price_usdt: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    price_stars: Mapped[int] = mapped_column(Integer, nullable=False)
    period_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default="30"
    )
    updated_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
