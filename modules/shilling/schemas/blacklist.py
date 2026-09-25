"""Pydantic-схемы чёрного списка каналов.

См. docs/neuroshilling-spec.md § 3.8.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, model_validator

from core.schemas.base import ORMModel


class BlacklistCreate(BaseModel):
    chat_id: Optional[int] = None
    username: Optional[str] = None
    reason: Optional[str] = None

    @model_validator(mode="after")
    def _at_least_one_identifier(self):
        if self.chat_id is None and not (self.username and self.username.strip()):
            raise ValueError("either chat_id or username must be provided")
        return self


class BlacklistRead(ORMModel):
    id: int
    campaign_id: int
    chat_id: Optional[int]
    username: Optional[str]
    reason: Optional[str]
    auto: bool
    created_at: datetime
    updated_at: datetime
