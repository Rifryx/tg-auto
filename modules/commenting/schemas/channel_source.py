"""Pydantic-схемы целевых каналов и черного списка (§ Этап 3)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from core.schemas.base import ORMModel

ChannelKind = Literal["username", "invite", "folder"]


def classify_channel_input(raw: str) -> ChannelKind:
    """Проверка типа ввода: @username | t.me/... | папка.

    Тонкая логика: если ссылка на addlist/list — folder; joinchat/+... —
    invite; @xxx или t.me/xxx (без спец-путей) — username.
    """
    v = raw.strip()
    low = v.lower()
    if "t.me/addlist/" in low or "t.me/list/" in low:
        return "folder"
    if "t.me/joinchat/" in low or "t.me/+" in low or low.startswith("+"):
        return "invite"
    return "username"


class CampaignChannelCreate(BaseModel):
    raw_input: str = Field(min_length=1, max_length=256)
    kind: Optional[ChannelKind] = None

    @model_validator(mode="after")
    def _fill_kind(self) -> "CampaignChannelCreate":
        if self.kind is None:
            self.kind = classify_channel_input(self.raw_input)
        return self


class CampaignChannelBulkCreate(BaseModel):
    """Bulk-добавление: несколько строк одним запросом (по одной в строке)."""

    raw_inputs: list[str] = Field(min_length=1, max_length=200)


class CampaignChannelRead(ORMModel):
    id: int
    campaign_id: int
    raw_input: str
    kind: ChannelKind
    resolved_chat_id: Optional[int]
    title: Optional[str]
    last_error: Optional[str]
    created_at: datetime
    updated_at: datetime


class ChannelBlacklistCreate(BaseModel):
    chat_id: Optional[int] = None
    username: Optional[str] = Field(default=None, max_length=128)
    reason: Optional[str] = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def _at_least_one(self) -> "ChannelBlacklistCreate":
        if self.chat_id is None and not (self.username or "").strip():
            raise ValueError("either chat_id or username must be provided")
        return self


class ChannelBlacklistRead(ORMModel):
    id: int
    campaign_id: int
    chat_id: Optional[int]
    username: Optional[str]
    reason: Optional[str]
    auto: bool
    created_at: datetime
    updated_at: datetime
