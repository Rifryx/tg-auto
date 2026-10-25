"""Pydantic-схемы продукта (базы знаний нейрошиллинга)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from core.schemas.base import ORMModel


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10_000)
    usp: Optional[str] = Field(default=None, max_length=500)
    website: Optional[str] = Field(default=None, max_length=500)
    tags: Optional[str] = Field(default=None, max_length=500)


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=10_000)
    usp: Optional[str] = Field(default=None, max_length=500)
    website: Optional[str] = Field(default=None, max_length=500)
    tags: Optional[str] = Field(default=None, max_length=500)


class ProductRead(ORMModel):
    id: int
    owner_user_id: str
    name: str
    description: str
    usp: Optional[str] = None
    website: Optional[str] = None
    tags: Optional[str] = None
    created_at: datetime
    updated_at: datetime
