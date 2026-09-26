"""ORM-модель роли внутри сценария (Инициатор, Ответчик, Скептик, …).

См. docs/neuroshilling-spec.md § 3.3.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import SHILLING_SCHEMA, Base


class ShillingScenarioRole(Base):
    __tablename__ = "scenario_roles"
    __table_args__ = ({"schema": SHILLING_SCHEMA},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    scenario_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SHILLING_SCHEMA}.scenarios.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    character: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Цвет карточки роли для фронта (hex или tailwind-tokens). Опционально.
    color: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
