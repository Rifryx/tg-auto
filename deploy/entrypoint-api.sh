#!/usr/bin/env sh
# Прод-entrypoint API (PROJECT-STAGES §6; аудит #10).
#
# Накатывает миграции ПЕРЕД стартом сервера, чтобы прод-контейнер сам приводил
# схему БД к head (раньше alembic upgrade делался только вручную / в тестовом
# conftest — в проде был риск рассинхрона схемы и кода).
#
# Использование (Docker CMD или напрямую):
#   deploy/entrypoint-api.sh
set -eu

echo "[entrypoint-api] alembic upgrade head"
alembic upgrade head

echo "[entrypoint-api] starting gunicorn"
exec gunicorn -c deploy/gunicorn.conf.py api.asgi:app
