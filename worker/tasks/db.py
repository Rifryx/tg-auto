"""Фабрика сессий БД для задач воркера."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def build_session_factory(dsn: str) -> sessionmaker:
    engine = create_engine(dsn, future=True)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
