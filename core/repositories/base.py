from __future__ import annotations

from typing import Generic, Optional, Type, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Общий предок репозиториев: держит сессию и модель.

    Репозиторий — единственная точка SQL-запросов в системе. ORM-логика вне
    репозиториев не допускается (см. архитектурные правила Core).
    """

    model: Type[ModelT]

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, id_: int) -> Optional[ModelT]:
        return self.session.get(self.model, id_)

    def list_all(self) -> list[ModelT]:
        return list(self.session.execute(select(self.model)).scalars().all())

    def _add(self, obj: ModelT) -> ModelT:
        self.session.add(obj)
        self.session.flush()
        return obj
