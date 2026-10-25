"""База знаний «Продукты» нейрошиллинга.

Один продукт описывается один раз (name/USP/website/description) и может
быть привязан к любому количеству кампаний через ``shilling.campaigns.product_id``.
Это убирает дублирование brand_name/brand_link/topic в каждой кампании и
даёт LLM-рерайтингу общий контекст продвижения.

Создаётся миграцией 0064_shilling_products.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import SHILLING_SCHEMA, Base


class ShillingProduct(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("length(name) >= 1", name="product_name_not_empty"),
        {"schema": SHILLING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=""
    )
    usp: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    tags: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
