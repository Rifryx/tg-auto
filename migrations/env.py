from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from core.models import COMMENTING_SCHEMA, SHILLING_SCHEMA, Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Приоритет URL БД:
#   1) DATABASE_URL из окружения — явный override;
#   2) sqlalchemy.url, если его ЯВНО задали в конфиге (напр. тестовый conftest);
#   3) иначе (в alembic.ini лежит дефолт-заглушка) — из конфигурации приложения
#      (core.config читает .env), чтобы bare `alembic upgrade head` ходил в ту же
#      БД, что API/воркер, а не в localhost:5432 из alembic.ini.
_INI_DEFAULT_URL = "postgresql+psycopg://neuro:neuro@localhost:5432/neuro"

db_url_env = os.getenv("DATABASE_URL")
if db_url_env:
    config.set_main_option("sqlalchemy.url", db_url_env)
else:
    current = config.get_main_option("sqlalchemy.url")
    if not current or current == _INI_DEFAULT_URL:
        try:
            from core.config import get_settings

            config.set_main_option("sqlalchemy.url", get_settings().database_url)
        except Exception:  # noqa: BLE001 - падать на резолве URL нельзя, оставим ini
            pass

target_metadata = Base.metadata

# alembic autogenerate по умолчанию видит только схему `public`. Отдаём ему
# явно ту схему, в которой живут таблицы модуля commenting.
KNOWN_SCHEMAS = {COMMENTING_SCHEMA, SHILLING_SCHEMA}


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name in {None, "public"} | KNOWN_SCHEMAS
    return True


def _ensure_schemas(connection) -> None:
    for schema in KNOWN_SCHEMAS:
        connection.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _ensure_schemas(connection)
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_name,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
