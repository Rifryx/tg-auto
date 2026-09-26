"""ORM-модель сценария (набор ролей и шагов диалога).

Сценарий отвязан от одной кампании: одну и ту же схему диалога можно
переиспользовать через ``is_template=True``, а поле ``campaign_id`` в
конкретной раскатке ссылается на «оригинал». См. docs/neuroshilling-spec.md
§ 3.2.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import SHILLING_SCHEMA, Base, TimestampMixin


class ShillingScenario(Base, TimestampMixin):
    __tablename__ = "scenarios"
    __table_args__ = (
        CheckConstraint(
            "persons_count >= 2",
            name="persons_count_valid",
        ),
        {"schema": SHILLING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # NULL для шаблонов, которые ещё не привязаны к кампании (маркетплейс).
    # SET NULL при удалении кампании — сохраняем сценарий, чтобы можно было
    # переиспользовать в другой.
    campaign_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey(f"{SHILLING_SCHEMA}.campaigns.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_template: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    persons_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2, server_default="2"
    )
    ai_generated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
