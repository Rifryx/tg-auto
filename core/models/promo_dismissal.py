"""Отметка «пользователь скрыл шторку акции».

Шторка-уведомление показывается один раз на каждую акцию: как только
пользователь закрыл её крестиком, пишем сюда строку, и ``GET /billing/promo``
перестаёт возвращать эту акцию этому пользователю. Хранение серверное (а не в
localStorage) — чтобы скрытие работало на всех устройствах пользователя.

Новая акция = новый ``promo_id`` ⇒ шторка снова покажется.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class PromoDismissal(Base):
    __tablename__ = "promo_dismissals"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    promo_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    dismissed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
