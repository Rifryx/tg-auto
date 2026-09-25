"""ORM-модель шага диалога (одна реплика или реакция).

Шаги упорядочены полем ``step_order`` в рамках одного сценария.
``reply_to_step_id`` образует внутренние ссылки-цитаты (Telegram reply).

См. docs/neuroshilling-spec.md § 3.4.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import SHILLING_SCHEMA, Base


class ShillingScenarioStep(Base):
    __tablename__ = "scenario_steps"
    __table_args__ = (
        CheckConstraint(
            "step_type IN ('message', 'reaction')",
            name="step_type_allowed",
        ),
        # Для message нужен непустой text; для reaction — reaction_emoji.
        CheckConstraint(
            "(step_type = 'message' AND text IS NOT NULL) OR "
            "(step_type = 'reaction' AND reaction_emoji IS NOT NULL)",
            name="step_payload_matches_type",
        ),
        CheckConstraint(
            "delay_before_sec IS NULL OR delay_before_sec >= 0",
            name="delay_before_sec_valid",
        ),
        {"schema": SHILLING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    scenario_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SHILLING_SCHEMA}.scenarios.id", ondelete="CASCADE"),
        nullable=False,
    )
    role_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SHILLING_SCHEMA}.scenario_roles.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(
        String, nullable=False, default="message", server_default="message"
    )
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # SET NULL при удалении referenced-шага: ответ станет обычной репликой,
    # диалог не разваливается.
    reply_to_step_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey(f"{SHILLING_SCHEMA}.scenario_steps.id", ondelete="SET NULL"),
        nullable=True,
    )
    delay_before_sec: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reaction_emoji: Mapped[Optional[str]] = mapped_column(String, nullable=True)
