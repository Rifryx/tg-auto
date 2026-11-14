"""Привязка аккаунта-инициатора к кампании масс-реакций.

Пул аккаунтов кампании + runtime-счётчики (как ``PrimingCampaignAccount``).
UNIQUE (campaign_id, account_id) защищает от дублей.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import MASS_REACTIONS_SCHEMA, Base, CreatedAtMixin
from modules.mass_reactions.schemas.enums import MassReactionAccountState


class MassReactionCampaignAccount(Base, CreatedAtMixin):
    __tablename__ = "campaign_accounts"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "account_id",
            name="uq_campaign_accounts_campaign_id_account_id",
        ),
        CheckConstraint(
            "state IN ("
            + ", ".join(f"'{m.value}'" for m in MassReactionAccountState)
            + ")",
            name="state_allowed",
        ),
        CheckConstraint(
            "flood_waits_consecutive >= 0 AND flood_waits_total >= 0",
            name="flood_counters_nonneg",
        ),
        CheckConstraint(
            "reactions_today >= 0 AND reactions_total >= 0",
            name="reaction_counters_nonneg",
        ),
        {"schema": MASS_REACTIONS_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{MASS_REACTIONS_SCHEMA}.campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )

    state: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=MassReactionAccountState.IDLE.value,
        server_default=MassReactionAccountState.IDLE.value,
    )

    flood_waits_consecutive: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    flood_waits_total: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    reactions_today: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    reactions_total: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    last_reaction_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_available_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Точка отсчёта warmup-рампы — ставится при первом включении в работу.
    warmup_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
