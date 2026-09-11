"""Сессия SQLAlchemy как FastAPI-зависимость.

Фабрика сессий строится лениво из ``core.config`` (DATABASE_URL) и кэшируется на
процесс. В тестах ``get_session`` переопределяется через ``dependency_overrides``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import get_settings


@lru_cache
def _session_factory() -> sessionmaker:
    engine = create_engine(get_settings().database_url, future=True)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def get_session() -> Iterator[Session]:
    session = _session_factory()()
    try:
        yield session
    finally:
        session.close()
