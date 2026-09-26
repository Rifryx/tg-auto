"""Лог выполнения шага сценария в конкретной цели.

Каждая запись — попытка отправить одну реплику/реакцию одним аккаунтом
в один целевой канал. Служит основой для статистики, дебага, failover
и инсайт-панели истории.

См. docs/neuroshilling-spec.md § 3.7.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import SHILLING_SCHEMA, Base, CreatedAtMixin


class ShillingExecutionLog(Base, CreatedAtMixin):
    __tablename__ = "execution_logs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('sent', 'failed', 'skipped', 'replaced')",
            name="ck_execution_logs_status_allowed",
        ),
        {"schema": SHILLING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{SHILLING_SCHEMA}.campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Цель может быть удалена, но лог остаётся исторически.
    target_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey(f"{SHILLING_SCHEMA}.campaign_targets.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Аккаунт удаляется каскадом (retire/purge), лог тоже.
    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    role_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey(f"{SHILLING_SCHEMA}.scenario_roles.id", ondelete="SET NULL"),
        nullable=True,
    )
    step_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey(f"{SHILLING_SCHEMA}.scenario_steps.id", ondelete="SET NULL"),
        nullable=True,
    )
    message_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    posted_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
