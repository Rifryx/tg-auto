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


class TargetCreate(BaseModel):
    raw_input: str = Field(min_length=1)
    kind: TargetKind = "username"


class TargetBulkCreate(BaseModel):
    """Bulk-добавление одной строкой на цель. Дубли пропускаются на уровне
    репозитория (UNIQUE-констрейнт)."""

    raw_inputs: list[str] = Field(min_length=1)


class TargetRead(ORMModel):
    id: int
    campaign_id: int
    raw_input: str
    kind: TargetKind
    resolved_chat_id: Optional[int]
    title: Optional[str]
    status: TargetStatus
    last_error: Optional[str]
    created_at: datetime
