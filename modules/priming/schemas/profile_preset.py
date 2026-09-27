"""Pydantic-схемы профиль-пресетов (spec §4.5)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import Field

from modules.priming.schemas.common import PrimingBaseModel
from modules.priming.schemas.enums import AvatarSource, UsernameGenerator


class ProfilePresetCreate(PrimingBaseModel):
    owner_user_id: int
    name: str = Field(..., min_length=1, max_length=120)
    first_name_pool: list[str] = Field(default_factory=list, max_length=1000)
    last_name_pool: list[str] = Field(default_factory=list, max_length=1000)
    username_generator: UsernameGenerator = UsernameGenerator.LLM
    bio_text: Optional[str] = Field(default=None, max_length=140)
    bio_link: Optional[str] = Field(default=None, max_length=512)
    avatar_source: AvatarSource = AvatarSource.UPLOAD
    stories_pool_id: Optional[int] = None
    anchor_channel_template_id: Optional[int] = None


class ProfilePresetUpdate(PrimingBaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    first_name_pool: Optional[list[str]] = Field(default=None, max_length=1000)
    last_name_pool: Optional[list[str]] = Field(default=None, max_length=1000)
    username_generator: Optional[UsernameGenerator] = None
    bio_text: Optional[str] = Field(default=None, max_length=140)
    bio_link: Optional[str] = Field(default=None, max_length=512)
    avatar_source: Optional[AvatarSource] = None
    stories_pool_id: Optional[int] = None
    anchor_channel_template_id: Optional[int] = None


class ProfilePresetRead(PrimingBaseModel):
    id: int
    owner_user_id: int
    name: str
    first_name_pool: list[str]
    last_name_pool: list[str]
    username_generator: UsernameGenerator
    bio_text: Optional[str] = None
    bio_link: Optional[str] = None
    avatar_source: AvatarSource
    stories_pool_id: Optional[int] = None
    anchor_channel_template_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class ApplyPresetRequest(PrimingBaseModel):
    """Запрос POST /accounts/{account_id}/apply-preset (spec §6)."""

    preset_id: int
    steps: list[str] = Field(
        default_factory=lambda: [
            "identity", "avatar", "bio", "stories", "anchor",
        ],
        min_length=1,
    )


class ApplyPresetJob(PrimingBaseModel):
    """Ответ на запрос применения пресета — id фоновой arq-задачи."""

    job_id: str
