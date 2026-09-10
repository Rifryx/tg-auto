"""Модели модуля ``commenting``.

Живут в отдельной Postgres-схеме ``commenting`` (не путать с Python-пакетом
``modules/commenting`` — здесь только ORM-классы, поскольку реестр модулей ещё
не выделен и на этапе 1 таблицы монтируются явно).
"""

from datetime import time
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import COMMENTING_SCHEMA, Base, CreatedAtMixin, TimestampMixin


class Campaign(Base, TimestampMixin):
    __tablename__ = "campaigns"
    __table_args__ = (
        CheckConstraint(
            "llm_provider IN ('deepseek', 'gemini')",
            name="llm_provider_allowed",
        ),
        CheckConstraint(
            "posting_delay_min_sec >= 0 AND posting_delay_max_sec >= posting_delay_min_sec",
            name="posting_delay_range_valid",
        ),
        {"schema": COMMENTING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    target_channel: Mapped[str] = mapped_column(String, nullable=False)
    discussion_group_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    base_system_prompt: Mapped[str] = mapped_column(String, nullable=False)
    llm_provider: Mapped[str] = mapped_column(String, nullable=False)
    active_hours_start: Mapped[time] = mapped_column(Time, nullable=False)
    active_hours_end: Mapped[time] = mapped_column(Time, nullable=False)
    active_hours_tz: Mapped[str] = mapped_column(String, nullable=False)
    posting_delay_min_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    posting_delay_max_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


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


class CommentLog(Base, CreatedAtMixin):
    __tablename__ = "comment_logs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('posted', 'failed', 'flagged')",
            name="status_allowed",
        ),
        Index(
            "ix_comment_logs_campaign_id_created_at",
            "campaign_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_comment_logs_account_id_created_at",
            "account_id",
            text("created_at DESC"),
        ),
        Index("ix_comment_logs_post_channel_msg_id", "post_channel_msg_id"),
        {"schema": COMMENTING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
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
    post_channel_msg_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    posted_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    comment_text: Mapped[str] = mapped_column(String, nullable=False)
    in_reply_to_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
