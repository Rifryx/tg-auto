"""Pydantic-схемы для API пула asset'ов (этап 6, backlog #1)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


AssetKind = Literal["avatar", "first_name", "last_name", "bio", "username_template"]


class ProfileAssetCreate(BaseModel):
    kind: AssetKind
    value: Optional[str] = Field(default=None, max_length=512)
    binary_b64: Optional[str] = None
    mime: Optional[str] = None
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_content(self) -> "ProfileAssetCreate":
        if self.kind == "avatar":
            if not self.binary_b64:
                raise ValueError("avatar requires binary_b64")
            if self.value:
                raise ValueError("avatar does not accept value")
        else:
            if not self.value:
                raise ValueError(f"{self.kind} requires value")
            if self.binary_b64:
                raise ValueError(f"{self.kind} does not accept binary_b64")
        return self


class ProfileAssetRead(BaseModel):
    id: int
    kind: str
    value: Optional[str]
    mime: Optional[str]
    tags: list[str]
    used_count: int
    created_at: datetime
    # Байты аватарки не отдаём наружу — только флаг, что они есть.
    has_binary: bool

    model_config = {"from_attributes": False}
