"""Привязка аккаунта к кампании (эксклюзивная: account_id UNIQUE)."""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import COMMENTING_SCHEMA, Base, CreatedAtMixin


class CampaignAccount(Base, CreatedAtMixin):
    __tablename__ = "campaign_accounts"
    __table_args__ = (
        PrimaryKeyConstraint("campaign_id", "account_id", name="pk_campaign_accounts"),
        UniqueConstraint("account_id", name="uq_campaign_accounts_account_id"),
        CheckConstraint(
            "probability_override IS NULL OR "
            "probability_override BETWEEN 0 AND 100",
            name="campaign_accounts_probability_override_valid",
        ),
        {"schema": COMMENTING_SCHEMA},
    )

    campaign_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{COMMENTING_SCHEMA}.campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    override_prompt: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Пер-аккаунтная вероятность для post_selection_mode='probability'
    # (§ Этап 2). NULL → используется campaign.probability_percent.
    probability_override: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Последний коммент аккаунта в этой кампании — для pause_between_sec.
    last_posted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
