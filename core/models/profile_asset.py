"""Модель пула asset'ов профиля (этап 6, backlog #1).

Хранит готовые значения оформления (аватарки/имена/био/username-шаблоны),
из которых bulk-action ``apply_profile_pool`` выбирает случайные.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ProfileAsset(Base):
    __tablename__ = "profile_assets"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('avatar', 'first_name', 'last_name', 'bio', 'username_template')",
            name="profile_asset_kind_allowed",
        ),
        # "binary" — зарезервированное слово Postgres, в сыром SQL — в кавычках.
        CheckConstraint(
            '(value IS NOT NULL) OR ("binary" IS NOT NULL)',
            name="profile_asset_has_content",
        ),
        CheckConstraint(
            'NOT (value IS NOT NULL AND "binary" IS NOT NULL)',
            name="profile_asset_single_content",
        ),
        Index("ix_profile_assets_user_kind", "user_id", "kind"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    binary: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    mime: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    tags: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    used_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
