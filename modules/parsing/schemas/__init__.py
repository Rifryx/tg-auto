"""Pydantic-схемы модуля парсинга (промпт 3.2b)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from modules.priming.schemas.enums import ParserSourceKind, TargetLastSeen


class _ParsingBase(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        extra="forbid",
    )


class ParsedListRead(_ParsingBase):
    id: int
    owner_user_id: int
    name: str
    source_kind: ParserSourceKind
    chat_ref: Optional[str] = None
    days_window: Optional[int] = None
    min_messages: Optional[int] = None
    raw_count: int
    after_filters_count: int
    filters_breakdown: dict = Field(default_factory=dict)
    parsed_at: Optional[datetime] = None
    created_at: datetime


class ParsedListTargetRead(_ParsingBase):
    id: int
    list_id: int
    tg_user_id: Optional[int] = None
    username: Optional[str] = None
    phone: Optional[str] = None
    has_premium: Optional[bool] = None
    last_seen_bucket: TargetLastSeen
    created_at: datetime


class RunChatMessagesRequest(_ParsingBase):
    name: str = Field(..., min_length=1, max_length=120)
    collector_account_id: int
    chat_ref: str = Field(..., min_length=1)
    days_window: int = Field(default=14, ge=1, le=60)
    min_messages: int = Field(default=1, ge=1)
    require_username: bool = True
    premium_only: bool = False


class RunChatMembersRequest(_ParsingBase):
    name: str = Field(..., min_length=1, max_length=120)
    collector_account_id: int
    chat_ref: str = Field(..., min_length=1)
    only_recently_seen: bool = True
    require_username: bool = True
    premium_only: bool = False


__all__ = [
    "ParsedListRead",
    "ParsedListTargetRead",
    "RunChatMessagesRequest",
    "RunChatMembersRequest",
]
