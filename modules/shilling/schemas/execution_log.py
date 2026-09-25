"""Pydantic-схемы лога выполнения.

См. docs/neuroshilling-spec.md § 3.7.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

from core.schemas.base import ORMModel

ExecutionStatus = Literal["sent", "failed", "skipped", "replaced"]


class ExecutionLogCreate(BaseModel):
    """Внутренний формат — используется воркером при записи попытки шага."""

    campaign_id: int
    target_id: Optional[int] = None
    account_id: int
    role_id: Optional[int] = None
    step_id: Optional[int] = None
    message_text: Optional[str] = None
    posted_message_id: Optional[int] = None
    status: ExecutionStatus
    error: Optional[str] = None


class ExecutionLogRead(ORMModel):
    id: int
    campaign_id: int
    target_id: Optional[int]
    account_id: int
    role_id: Optional[int]
    step_id: Optional[int]
    message_text: Optional[str]
    posted_message_id: Optional[int]
    status: ExecutionStatus
    error: Optional[str]
    created_at: datetime
