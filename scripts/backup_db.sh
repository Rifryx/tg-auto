#!/usr/bin/env bash
# Снимок БД из docker-контейнера postgres в один SQL-файл.
#
# Используйте ПЕРЕД любой чисткой Docker (удаление контейнеров/volumes,
# "Clean/Purge data", перенос WSL-диска и т.п.) — эти операции стирают
# volume postgres_data безвозвратно, бэкап восстановить неоткуда, если
# не сделать его заранее.
#
# Запуск (из корня репозитория, контейнер postgres должен быть запущен):
#   bash scripts/backup_db.sh
#   # или на Windows через PowerShell с установленным bash (Git Bash/WSL):
#   bash scripts/backup_db.sh
#
# Восстановление:
#   bash scripts/restore_db.sh backups/neuro_2026-10-23_1200.sql

set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p backups
STAMP=$(date +%Y-%m-%d_%H%M)
OUT="backups/neuro_${STAMP}.sql"

echo "Снимаю бэкап базы 'neuro' в ${OUT}…"
docker compose exec -T postgres pg_dump -U neuro -d neuro --no-owner --no-privileges > "${OUT}"

SIZE=$(du -h "${OUT}" | cut -f1)
echo "Готово: ${OUT} (${SIZE})"
echo "Не забудьте скопировать этот файл куда-то ВНЕ Docker (на D:, в облако и т.п.) —"
echo "сам он лежит в рабочей копии репозитория и НЕ защищён от случайного удаления."
