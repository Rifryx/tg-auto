"""Привязка media_assets к кампании — картинки для attach_image (E4.1)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, PrimaryKeyConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import COMMENTING_SCHEMA, Base


class CampaignMediaAsset(Base):
    """M2M: какие media_assets прикладывать к комментариям этой кампании.

    Пользователь явно добавляет ассеты в кампанию через API. При отправке
    коммента с флагом attach_image берётся случайный ассет из этой таблицы.
    Пусто — картинка не приложится (флаг молча игнорируется в runtime).
    """

    __tablename__ = "campaign_media_assets"
    __table_args__ = (
        PrimaryKeyConstraint("campaign_id", "media_asset_id", name="pk_campaign_media_assets"),
        {"schema": COMMENTING_SCHEMA},
    )

    campaign_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(f"{COMMENTING_SCHEMA}.campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    media_asset_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("media_assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
