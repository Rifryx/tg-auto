"""Пресет оформления профиля-конверсии (spec §4.5).

Точка конверсии прайминга — сам аккаунт. Preset хранит шаблоны имени,
юзернейма, аватара, bio, ссылок на пул сторис и шаблон anchor-канала.

``stories_pool_id`` и ``anchor_channel_template_id`` — forward-refs на
таблицы, которые заводятся на этапе 4 (POC-визард); сейчас — nullable
BIGINT без FK-констрейнтов, чтобы миграция не ссылалась на несуществующие
таблицы. FK будут добавлены соответствующей миграцией промпта 4.x.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import PRIMING_SCHEMA, Base, TimestampMixin
from modules.priming.schemas.enums import AvatarSource, UsernameGenerator


class PrimingProfilePreset(Base, TimestampMixin):
    __tablename__ = "profile_presets"
    __table_args__ = (
        CheckConstraint(
            "username_generator IN ("
            + ", ".join(f"'{m.value}'" for m in UsernameGenerator)
            + ")",
            name="username_generator_allowed",
        ),
        CheckConstraint(
            "avatar_source IN ("
            + ", ".join(f"'{m.value}'" for m in AvatarSource)
            + ")",
            name="avatar_source_allowed",
        ),
        # Быстрый список пресетов пользователя (UI-каталог).
        Index("ix_profile_presets_owner", "owner_user_id"),
        {"schema": PRIMING_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    # Пулы имён и юзернеймов — JSONB со списком строк, конкретная форма
    # (например, шаблоны или веса) валидируется на уровне Pydantic-схемы.
    first_name_pool: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    last_name_pool: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    username_generator: Mapped[str] = mapped_column(
        String, nullable=False,
        default=UsernameGenerator.LLM.value,
        server_default=UsernameGenerator.LLM.value,
    )

    bio_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bio_link: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    avatar_source: Mapped[str] = mapped_column(
        String, nullable=False,
        default=AvatarSource.UPLOAD.value,
        server_default=AvatarSource.UPLOAD.value,
    )

    # forward-refs, FK будет добавлен позднее (см. модуль-docstring).
    stories_pool_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
    anchor_channel_template_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
