"""Лог опубликованных/неудачных комментариев (append-only)."""

from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import COMMENTING_SCHEMA, Base, CreatedAtMixin


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
