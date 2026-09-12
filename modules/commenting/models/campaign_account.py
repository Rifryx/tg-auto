"""Привязка аккаунта к кампании (эксклюзивная: account_id UNIQUE)."""

from typing import Optional

from sqlalchemy import (
    BigInteger,
    ForeignKey,
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
