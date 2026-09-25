# Neuro-Commenting

Панель управления Telegram-аккаунтами: логин, прогрев (created → warming → pool),
пул и модуль комментирования. Backend — FastAPI (API) + arq-воркер (Telethon,
LLM), Postgres, Redis. Frontend — Telegram Mini App (React + Vite), раздаётся
через nginx на одном origin с API.

Архитектура и инварианты — в [system-design.md](system-design.md),
[docs/PROJECT-STAGES.md](docs/PROJECT-STAGES.md); визуальный язык фронта —
[docs/UI-DESIGN-BRIEF.md](docs/UI-DESIGN-BRIEF.md).

## Запуск (Docker)

```bash
cp .env.example .env
```

Заполни в `.env` критичные поля:

- `ENCRYPTION_KEY` — свой ключ Fernet: `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"`.
- Для прод-режима: `DEV_MODE=false`, `TELEGRAM_API_ID`/`TELEGRAM_API_HASH`,
  хотя бы один из `DEEPSEEK_API_KEY`/`GEMINI_API_KEY`, `WEBAPP_ORIGIN`.
- С `DEV_MODE=true` (по умолчанию в примере) стек поднимается без реальных
  Telegram/LLM-ключей — удобно для локальной проверки.

Затем:

```bash
docker compose up -d
```

Поднимутся пять сервисов: `postgres`, `redis`, `api`, `worker`, `frontend`.
Все ждут `healthy` зависимостей; полный старт — в пределах ~90 секунд.

- **Frontend (Mini App):** http://localhost:3000
- **API:** http://localhost:8000 — проверка живости `curl http://localhost:8000/health`
  (200 только если реально доступны Postgres и Redis).
- Фронт ходит в API через `/api/*` (nginx-прокси на `api:8000`) — один origin,
  без CORS-проблем и с сохранением initData-заголовков.

### Миграции

Схему БД накатывает **только контейнер `api`** при старте
(`deploy/entrypoint-api.sh`: `alembic upgrade head && exec gunicorn …`).
Воркер миграции не трогает — так два процесса не мигрируют одновременно.

### Один воркер

Воркер запускается **в одном экземпляре** — инвариант «один Telethon-пул на
процесс» ([system-design.md §12](system-design.md)). Не задавай
`deploy.replicas > 1`.

### Данные

Postgres и Redis используют именованные volume (`postgres_data`, `redis_data`) —
данные переживают `docker compose down && docker compose up`. Полная очистка:
`docker compose down -v`.

### Логи

```bash
docker compose logs -f api       # старт, миграции, коннективность
docker compose logs -f worker    # логин/прогрев/комментирование, health-события
docker compose ps                # статусы и healthcheck
```

## Модуль «НейроШиллинг»

Координированные нативные диалоги нескольких аккаунтов в комментариях целевых
каналов: сценарий с ролями и репликами, ротация на резерв при банах, ИИ-рерайт
и генерация сценариев, сухой прогон с live-таймлайном. API — под префиксом
`/modules/shilling`, воркер — задачи `shilling.*`, схема БД — `shilling`.

Спецификация и план:
[docs/neuroshilling-spec.md](docs/neuroshilling-spec.md),
[docs/neuroshilling-ui-ux.md](docs/neuroshilling-ui-ux.md),
[docs/neuroshilling-prompts.md](docs/neuroshilling-prompts.md).

## Тесты

Тестам нужны отдельные Postgres/Redis (на портах 5433/6380):

```bash
docker compose --profile test up -d postgres_test redis_test
pip install -e ".[dev]"
pytest
```

## Прод-заметки

- `DEV_MODE=false` включает валидацию секретов и строгий CORS (`WEBAPP_ORIGIN`).
- Смени `ENCRYPTION_KEY` и пароль Postgres на реальные значения.
- Отложенные пункты (каталог интересов персоны, batch-retire) — в
  [docs/PROJECT.md](docs/PROJECT.md); статус связности — в
  [docs/INTEGRATION-AUDIT.md](docs/INTEGRATION-AUDIT.md).
