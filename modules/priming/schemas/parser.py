"""Pydantic-схемы запросов к парсеру аудитории (spec §6, §8)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import Field

from modules.priming.schemas.common import PrimingBaseModel
from modules.priming.schemas.enums import ParserSourceKind


class ChatMessagesParserParams(PrimingBaseModel):
    chat_ref: str = Field(..., min_length=1)
    days_window: int = Field(..., ge=1, le=60)
    min_messages: int = Field(default=1, ge=1)


class ChatMembersParserParams(PrimingBaseModel):
    chat_ref: str = Field(..., min_length=1)
    only_recently_seen: bool = True


class ParserRunRequest(PrimingBaseModel):
    """POST /campaigns/{id}/targets/parse (spec §6).

    ``kind`` определяет форму ``params``. FastAPI отдаёт 400 при
    несовпадении, сервисный слой (промпт 3.3) разбирает вариант.
    """

    kind: ParserSourceKind
    params: dict = Field(default_factory=dict)
    require_username: bool = True
    premium_only: bool = False


class ParserJobStatus(PrimingBaseModel):
    """Ответ на GET /parse-jobs/{job_id}."""

    job_id: str
    state: str  # queued / running / done / failed — сырой статус arq
    raw_count: int = 0
    after_filters_count: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None


class TargetSourceRead(PrimingBaseModel):
    id: int
    campaign_id: int
    kind: ParserSourceKind
    chat_ref: Optional[str] = None
    days_window: Optional[int] = None
    min_messages: Optional[int] = None
    raw_count: int
    after_filters_count: int
    parsed_at: Optional[datetime] = None
    created_at: datetime
