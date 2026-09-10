from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from core.schemas.base import ORMModel


class PersonaCreate(BaseModel):
    name: str
    avatar_template_url: Optional[str] = None
    bio_template: Optional[str] = None
    personality_tags: list[str] = Field(default_factory=list)


class PersonaUpdate(BaseModel):
    name: Optional[str] = None
    avatar_template_url: Optional[str] = None
    bio_template: Optional[str] = None
    personality_tags: Optional[list[str]] = None


class PersonaRead(ORMModel):
    id: int
    name: str
    avatar_template_url: Optional[str]
    bio_template: Optional[str]
    personality_tags: list[str]
    created_at: datetime
