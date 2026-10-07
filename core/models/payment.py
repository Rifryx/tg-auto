"""Платёж за подписку Pro — леджер (append-only по смыслу).

Одна строка = одна попытка оплаты (Stars или Crypto Bot). Строка создаётся в
статусе ``pending`` при создании инвойса, переходит в ``paid`` ровно один раз
(идемпотентно, под ``SELECT … FOR UPDATE`` — см. ``core.billing.payments``),
или в ``expired``/``failed``.

Ключевые гарантии против двойного списания и гонок:
* ``payload`` уникален — наш токен, который кладём в инвойс и получаем обратно
  в вебхуке/коллбэке провайдера; второй инвойс на тот же платёж невозможен.
* ``(provider, provider_invoice_id)`` уникален (partial, где invoice_id задан) —
  один инвойс провайдера не может породить два применённых платежа.
* ``applied_at`` ставится в той же транзакции, что и продление подписки.

``price_usdt``/``price_stars`` — СНИМОК цены на момент создания инвойса (с учётом
действовавшей тогда акции ``promo_id``). Пользователь платит ровно столько,
сколько ему показали, даже если акция закончится за время оплаты.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('stars', 'crypto')", name="provider_allowed"
        ),
        CheckConstraint(
            "status IN ('pending', 'paid', 'expired', 'failed')",
            name="status_allowed",
        ),
        UniqueConstraint("payload", name="uq_payments_payload"),
        # Один инвойс провайдера → максимум один платёж. Partial: pending Stars
        # до successful_payment ещё не имеет provider_invoice_id.
        Index(
            "uq_payments_provider_invoice",
            "provider",
            "provider_invoice_id",
            unique=True,
            postgresql_where=text("provider_invoice_id IS NOT NULL"),
        ),
        Index("ix_payments_status_provider", "status", "provider"),
        Index("ix_payments_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    provider_invoice_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Ссылка на оплату (Stars invoice link / CryptoBot pay_url). Храним, чтобы
    # переиспользуемый pending-инвойс можно было открыть повторно без второго
    # обращения к провайдеру.
    pay_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    payload: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )

    # Снимок того, что выставлено к оплате.
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    plan_id: Mapped[str] = mapped_column(String, nullable=False, server_default="pro")
    period_days: Mapped[int] = mapped_column(Integer, nullable=False)
    promo_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    price_usdt: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    price_stars: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    applied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
