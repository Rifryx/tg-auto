#!/usr/bin/env bash
# Восстановление БД из файла, созданного scripts/backup_db.sh.
#
# ВНИМАНИЕ: перезаписывает текущую базу 'neuro' целиком. Если в ней уже
# что-то есть и вы не хотите это терять — сначала сделайте свой бэкап
# (scripts/backup_db.sh).
#
# Запуск (контейнер postgres должен быть запущен):
#   bash scripts/restore_db.sh backups/neuro_2026-10-23_1200.sql

set -euo pipefail
cd "$(dirname "$0")/.."

FILE="${1:-}"
if [[ -z "$FILE" || ! -f "$FILE" ]]; then
  echo "Использование: bash scripts/restore_db.sh <путь-к-файлу.sql>" >&2
  echo "Доступные бэкапы:" >&2
  ls -1 backups/*.sql 2>/dev/null || echo "  (папка backups/ пуста)" >&2
  exit 1
fi

echo "Восстанавливаю базу 'neuro' из ${FILE}…"
echo "Текущие данные в 'neuro' будут перезаписаны. Продолжить? [y/N]"
read -r CONFIRM
if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
  echo "Отменено."
  exit 1
fi

docker compose exec -T postgres psql -U neuro -d neuro < "${FILE}"
echo "Готово."
