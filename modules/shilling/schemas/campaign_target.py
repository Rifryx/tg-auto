"""Pydantic-схемы целевых каналов кампании.

См. docs/neuroshilling-spec.md § 3.6.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from core.schemas.base import ORMModel

TargetKind = Literal["username", "invite", "chat_id"]
TargetStatus = Literal["pending", "resolved", "error"]
# Режим цели — что именно делаем со ссылкой (см. модель ShillingTarget).
TargetMode = Literal["link", "chat", "channel_post", "channel_monitor"]


class TargetCreate(BaseModel):
    raw_input: str = Field(min_length=1)
    kind: TargetKind = "username"
    mode: TargetMode = "link"
    post_id: Optional[int] = Field(default=None, gt=0)
    # Заводится автодискавери (тумблер «мониторить всё»), не руками.
    auto_discovered: bool = False


class TargetBulkCreate(BaseModel):
    """Bulk-добавление одной строкой на цель. Дубли пропускаются на уровне
    репозитория (UNIQUE-индекс по campaign_id+raw_input+post_id)."""

    raw_inputs: list[str] = Field(min_length=1)
    # Вкладка UI, из которой добавляют: «Чаты» / «Мониторинг каналов» /
    # «Ссылки» / «Посты каналов». Ссылка на конкретный пост (t.me/x/123)
    # всегда становится channel_post независимо от вкладки.
    mode: TargetMode = "link"


class TargetRead(ORMModel):
    id: int
    campaign_id: int
    raw_input: str
    kind: TargetKind
    mode: TargetMode = "link"
    post_id: Optional[int] = None
    last_seen_post_id: Optional[int] = None
    auto_discovered: bool = False
    resolved_chat_id: Optional[int]
    title: Optional[str]
    status: TargetStatus
    last_error: Optional[str]
    created_at: datetime
