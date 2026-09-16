from datetime import datetime, time
from typing import Optional

from pydantic import BaseModel, Field

from core.schemas.base import ORMModel


class PersonaCreate(BaseModel):
    name: str
    avatar_template_url: Optional[str] = None
    bio_template: Optional[str] = None
    personality_tags: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    timezone: Optional[str] = None
    active_hours_start: Optional[time] = None
    active_hours_end: Optional[time] = None


class PersonaUpdate(BaseModel):
    name: Optional[str] = None
    avatar_template_url: Optional[str] = None
    bio_template: Optional[str] = None
    personality_tags: Optional[list[str]] = None
    interests: Optional[list[str]] = None
    timezone: Optional[str] = None
    active_hours_start: Optional[time] = None
    active_hours_end: Optional[time] = None


class PersonaRead(ORMModel):
    id: int
    name: str
    avatar_template_url: Optional[str]
    bio_template: Optional[str]
    personality_tags: list[str]
    interests: list[str] = []
    timezone: Optional[str] = None
    active_hours_start: Optional[time] = None
    active_hours_end: Optional[time] = None
    created_at: datetime
