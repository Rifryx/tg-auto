from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEST_DSN = "postgresql+psycopg://neuro:neuro@localhost:5433/neuro_test"


def _test_dsn() -> str:
    return os.getenv("TEST_DATABASE_URL", DEFAULT_TEST_DSN)


@pytest.fixture(scope="session")
def engine():
    dsn = _test_dsn()
    eng = create_engine(dsn, future=True)

    with eng.connect() as conn:
        conn.execute(text('DROP SCHEMA IF EXISTS "commenting" CASCADE'))
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.commit()

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", dsn)
    command.upgrade(cfg, "head")

    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine) -> Session:
    # Внешняя транзакция + create_savepoint: код под тестом может звать
    # session.commit() (как делает AccountStateMachine), но всё остаётся внутри
    # savepoint'а и откатывается в teardown — изоляция между тестами сохранена.
    connection = engine.connect()
    transaction = connection.begin()
    Session_ = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        future=True,
        join_transaction_mode="create_savepoint",
    )
    session = Session_()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
