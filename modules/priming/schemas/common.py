"""Базовые Pydantic-схемы модуля прайминга.

Держатся отдельно от доменных схем (campaign / target / stats), чтобы
любой роутер модуля мог использовать их без циклов импорта.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


T = TypeVar("T")


class PrimingBaseModel(BaseModel):
    """Общий базовый класс: strict-режим + от-имени-orm атрибуты.

    Оставляем ``populate_by_name`` включённым, чтобы UI мог присылать поля
    как в camelCase, так и в snake_case (существующие модули так и делают).
    """

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        extra="forbid",
    )


class Pagination(PrimingBaseModel):
    """Классический page/size пагинатор.

    В отличие от keyset (который мы применим только к execution_log —
    промпт 6.4), большинство эндпоинтов кампаний работает по короткому
    списку и им хватает страничного пагинатора.
    """

    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=200)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size

    @property
    def limit(self) -> int:
        return self.size


class Page(PrimingBaseModel, Generic[T]):
    """Общий контейнер страницы: items + счётчики."""

    items: list[T]
    page: int
    size: int
    total: int


class TimeRange(PrimingBaseModel):
    """Замкнутый интервал ``[start, end]`` в UTC.

    Используется для фильтров логов и статистики. Открытые интервалы
    (``start=None`` / ``end=None``) допустимы: при отсутствии границы
    её просто нет в WHERE-выражении.
    """

    start: Optional[datetime] = None
    end: Optional[datetime] = None

    @model_validator(mode="after")
    def _validate_order(self) -> "TimeRange":
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("TimeRange.start must be <= TimeRange.end")
        return self


class ErrorEnvelope(PrimingBaseModel):
    """Единый формат ошибок API-слоя модуля.

    В FastAPI мы отдаём его как тело 4xx/5xx через ``HTTPException(detail=…)``
    или собственный exception handler (заведём на промпте 2.4).
    """

    error: str = Field(..., description="Машинный код ошибки, snake_case")
    message: str = Field(..., description="Человекочитаемое описание")
    details: Optional[dict[str, Any]] = None


__all__ = [
    "PrimingBaseModel",
    "Pagination",
    "Page",
    "TimeRange",
    "ErrorEnvelope",
]
