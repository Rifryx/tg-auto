# Neuro-Commenting — рабочие заметки

Актуальная спецификация: [docs/PROJECT-STAGES.md](docs/PROJECT-STAGES.md).

## Инварианты (нарушать нельзя)

Копия из PROJECT-STAGES.md, раздел 0, чтобы всегда были перед глазами:

1. Только Worker открывает `.session` / инстанцирует `TelegramClient`. API — никогда.
2. API ↔ Worker общаются только через Redis. Никаких прямых вызовов.
3. Фингерпринт задаётся на стадии `created` и не меняется никогда.
4. Один прокси = один аккаунт. Гео прокси = гео номера.
5. `accounts.status` меняется только через `AccountStateMachine`.
6. Аккаунт занят максимум одним контейнером.
7. Каждое исходящее Telegram-действие проходит через rate-limit governor.
8. Postgres — источник правды. Redis — очередь, pub/sub, TTL-счётчики.
9. Модули зависят от Core, не наоборот.
10. Мягкое удаление не используется.

## Открытые TODO (замечены при проектировании моделей, не решены сейчас)

- **Иммутабельность фингерпринта.** В спеке зафиксировано, что `device_model` /
  `system_version` / `app_version` / `lang_code` / `system_lang_code` неизменны
  после стадии `created`. Контроль оставлен сервисному слою (репозиторий/state
  machine). На уровне БД триггер не ставим — решить, нужен ли он в v2.
- **Эксклюзивность назначения аккаунта в контейнер.** CHECK
  `(assigned_container_type IS NULL) = (assigned_container_id IS NULL)` есть.
  «Один контейнер на аккаунт» — гарантируется сервисом. При появлении второго
  модуля вернуться и оценить, нужен ли partial UNIQUE index
  `(assigned_container_type, assigned_container_id) WHERE status='assigned'`.
- **Уникальность на уровне модуля commenting** уже есть:
  `UNIQUE(campaign_accounts.account_id)`.
- **`triggered_status_change`** в `health_events` — свободный текст (`"pool→cooldown"`).
  Формализовать в enum, если появится агрегация по этому полю.
- **`account.previous_status`** не покрыт CHECK — теоретически туда попадёт что
  угодно. Решить: расширять ли CHECK или оставлять контроль в state machine
  (сейчас — state machine).
- **`account_status_history.reason`** — свободный текст (`account.created`,
  `warming.start`, ...). Список зафиксирован в spec. Решить: enum vs CHECK vs
  свободный текст (сейчас — свободный, ловится state machine'ой).

## Как поднять окружение

```bash
docker compose up -d postgres postgres_test
pip install -e .[dev]
alembic upgrade head
pytest
```

## Как запустить только тесты

Тестовая БД поднимается в `docker-compose.yml` как `postgres_test` на порту 5433:

```bash
docker compose up -d postgres_test
pytest
```

DSN по умолчанию: `postgresql+psycopg://neuro:neuro@localhost:5433/neuro_test`
(перекрыть можно `TEST_DATABASE_URL`).
