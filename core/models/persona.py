from typing import Any, Optional

from sqlalchemy import BigInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base, CreatedAtMixin


class Persona(Base, CreatedAtMixin):
    __tablename__ = "personas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    avatar_template_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    bio_template: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    personality_tags: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
