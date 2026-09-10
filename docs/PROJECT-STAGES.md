# Neuro-Commenting — проектный документ по этапам разработки

Собрано из `system-design.md` (v2), `detailed-design.md`, `neurocommentingroadmap.md`.
Назначение: единый источник правды, разбитый по этапам, чтобы скармливать Claude Code только актуальный раздел.

> **Важно про рассинхрон документов.** В роадмапе стадии названы `active`/`limited`/`cooldown`.
> В system-design v2 и detailed-design они заменены на `pool`/`assigned`/`cooldown` (+ `warming`, `created`, `retired`, `banned`).
> **Истина — v2:** `created → warming → pool ↔ assigned → cooldown → (возврат в previous_status)`, терминальные — `retired`/`banned`.
> Где роадмап противоречит v2 — всегда побеждает v2.

---

## 0. Глобальные правила (идут в PROJECT.md, видны на каждом промпте)

### Инварианты (нарушать нельзя)

1. Только Worker открывает `.session` / инстанцирует TelegramClient. API — никогда.
2. API ↔ Worker общаются только через Redis (очередь команд + pub/sub). Никаких прямых вызовов.
3. Фингерпринт (`device_model`, `system_version`, `app_version`, `lang_code`, `system_lang_code`) задаётся на стадии `created` и **не меняется никогда**.
4. Один прокси = один аккаунт. Гео прокси = гео номера. Языки (`lang_code`/`system_lang_code`) согласованы с гео.
5. `accounts.status` меняется ТОЛЬКО через `AccountStateMachine`. Репозиторий не имеет метода `update_status`.
6. Аккаунт в один момент занят максимум одним контейнером (эксклюзивность). Смена контейнера = явный detach → pool → attach.
7. Каждое исходящее действие Telegram проходит через rate-limit governor.
8. Postgres — источник правды по состоянию. Redis — очередь, pub/sub, rate-limit-счётчики (TTL). Redis не хранит историю.
9. Модули (commenting, parser) зависят от Core, не наоборот. Core не импортирует модули (реестр отложен до второго модуля).
10. Мягкое удаление не используется. Аккаунты уходят в `retired`/`banned`, но остаются в БД.

### Стек (зафиксирован)

- Backend: FastAPI (Python 3.11+), процессы `api/` и `worker/` раздельно
- Telegram: Telethon, фингерпринт передаётся в каждый `TelegramClient(...)` из сохранённых полей БД
- БД: Postgres + alembic; модули — в Postgres-схемах (`commenting.*`)
- Очередь: Redis + arq (одна очередь `arq:queue`, high-приоритет отложен)
- LLM: DeepSeek (OpenAI-совместимый) и/или Gemini free tier, выбор на уровне кампании
- Frontend: React, Telegram Mini App, авторизация по initData
- Шифрование сессий/паролей: Fernet (или аналог), ключ из ENV

### Структура репо (монорепо)

```
core/          # shared: config, models, enums, schemas, repositories, crypto, queue, state_machine
api/           # FastAPI: deps (initData), routers, services (эмиттеры команд)
worker/        # отдельный процесс: main, client_pool, fingerprint, login, warming, health, llm, tasks
modules/
  commenting/  # models, api, worker, register.py (frontend отдельно в frontend/src/modules/)
frontend/      # React Mini App: app, screens (shared), modules, shared
migrations/    # alembic
docs/          # PROJECT-STAGES.md и прочие
```

### Главный приоритет продукта

Выживаемость аккаунтов > всего остального. Аккаунты — расходник, ничего ценного на них нет.
Автоматизация юзер-аккаунтов против ToS Telegram — это игра в кошки-мышки; прогрев и health-монитор снижают риск, не убирают его.

---

## Этап 1. Данные и Core

### 1.1 Стадии аккаунта

| Стадия | Смысл | Можно назначить в контейнер? |
|--------|-------|------------------------------|
| `created` | Сессия есть, фингерпринт зафиксирован, прокси привязан. Логин только завершён или не завершён. | Нет |
| `warming` | Первичный прогрев до готовности, идёт по расписанию. | Нет |
| `pool` | Свободен, в библиотеке. Идёт поддерживающий прогрев по пресету. | **Да** |
| `assigned` | Занят одним контейнером (`assigned_container_type` + `assigned_container_id` не NULL). | Уже занят |
| `cooldown` | Отдых после инцидента, до `cooldown_until`. `previous_status` — куда вернётся. | Нет |
| `retired` | Ручной вывод из работы. | Нет |
| `banned` | Забанен Telegram. Терминальная. | Нет |

### 1.2 Таблица переходов state machine

Инициатор: `user` (Mini App), `auto` (воркер), `health` (health-монитор). Каждый переход пишется в `account_status_history`.

| Из | В | Событие | Инициатор | Побочные эффекты |
|----|---|---------|-----------|------------------|
| — | `created` | `account.created` | user | Зафиксирован фингерпринт, привязан прокси |
| `created` | `warming` | `warming.start` | auto | `warming_started_at`, старт джобы прогрева |
| `warming` | `pool` | `warming.completed` | auto | `activated_at`, далее поддерживающий прогрев |
| `pool` | `assigned` | `container.attach` | user | Заполнены `assigned_container_*`, поддерживающий прогрев приостановлен |
| `assigned` | `pool` | `container.detach` | user | Очищены `assigned_container_*`, прогрев возобновлён |
| `pool` | `cooldown` | `health.incident` | health | `previous_status=pool`, `cooldown_until`, HealthEvent |
| `assigned` | `cooldown` | `health.incident` | health | `previous_status=assigned` (контейнер помнится) |
| `cooldown` | `pool` | `cooldown.expired` | auto | Только если `previous_status=pool` |
| `cooldown` | `assigned` | `cooldown.expired` | auto | Только если `previous_status=assigned` и контейнер существует |
| любая (кроме `banned`) | `retired` | `account.retire` | user | Если был `assigned` — сначала автоматический detach |
| любая | `banned` | `health.ban_detected` | health | Терминально. `assigned_container_*` очищены |
| `banned` | `retired` | `account.acknowledge_ban` | user | Ручной, убрать из активных алертов |

**Запрещено:** `banned → *` кроме `retired`; `pool → warming` (обратного пути нет — сломанный аккаунт идёт в retired/banned); прямой `assigned → assigned` (только через pool).

### 1.3 Схема БД (Postgres, все id bigint autoincrement, таймстампы timestamptz)

**Shared (public):**

`proxies`: id, host, port, login NULL, password_enc bytea NULL, type (`socks5`|`http`), geo NULL (ISO страна), status (`alive`|`dead`|`unchecked`), last_checked_at NULL, created_at, updated_at. Индекс `(status)`.

`personas`: id, name, avatar_template_url NULL, bio_template NULL, personality_tags jsonb (массив строк), created_at.

`accounts`:
- phone text UNIQUE, username NULL, bio NULL, avatar_url NULL
- session_enc bytea (зашифрованная `.session`)
- proxy_id FK NULL, persona_id FK NULL
- status, previous_status NULL
- assigned_container_type NULL (напр. `commenting`), assigned_container_id NULL
- warming_profile (`minimal`|`medium`|`dense`, default `medium`), warming_started_at NULL, activated_at NULL, cooldown_until NULL
- device_model, system_version, app_version, lang_code, system_lang_code — фингерпринт, immutable после `created`
- created_at, updated_at

CHECK: status IN (created, warming, pool, assigned, cooldown, retired, banned); warming_profile IN (minimal, medium, dense); `(assigned_container_type IS NULL) = (assigned_container_id IS NULL)`.
Индексы: `(status)`; `(status, warming_profile) WHERE status='pool'`; `(assigned_container_type, assigned_container_id)`; `(cooldown_until) WHERE status='cooldown'`; `(proxy_id)`; `(persona_id)`.
Эксклюзивность назначения — на уровне сервиса.

`warming_activities`: id, account_id FK, kind (`initial`|`maintenance`), action_type (`subscribe_channel`|`read_history`|`reaction`|`view_media`|`join_group`|`idle_online`|`update_profile`), target NULL (id канала/чата/сообщения), status (`done`|`failed`|`skipped`), meta jsonb NULL, created_at. Индексы: `(account_id, created_at DESC)`, `(kind, created_at)`.

`health_events`: id, account_id FK, event_type (`flood_wait`|`spam_block`|`restricted`|`proxy_down`|`session_revoked`|`auth_failed`), meta jsonb NULL (напр. floodwait секунды), resolved bool default false, triggered_status_change NULL (напр. `pool→cooldown`), created_at, resolved_at NULL. Индексы: `(account_id, created_at DESC)`, `(resolved) WHERE resolved=false`.

`account_status_history`: id, account_id FK, from_status NULL (NULL при создании), to_status, reason (код события), initiator (`user`|`auto`|`health`), meta jsonb NULL, created_at. Индекс `(account_id, created_at DESC)`.

**Модуль commenting (схема `commenting`):**

`commenting.campaigns`: id, name, target_channel (text, @username или id), discussion_group_id bigint NULL (заполняется автоматически), base_system_prompt, llm_provider (`deepseek`|`gemini`), active_hours_start time, active_hours_end time, active_hours_tz (напр. `Europe/Kiev`), posting_delay_min_sec int, posting_delay_max_sec int, enabled bool default true, created_at, updated_at.

`commenting.campaign_accounts`: campaign_id FK, account_id FK **UNIQUE** (аккаунт максимум в одной кампании), override_prompt NULL, created_at. PK (campaign_id, account_id).

`commenting.comment_logs`: id, campaign_id FK, account_id FK, post_channel_msg_id bigint, posted_message_id NULL, comment_text, in_reply_to_message_id NULL (тред-симуляция), status (`posted`|`failed`|`flagged`), error NULL, created_at. Индексы: `(campaign_id, created_at DESC)`, `(account_id, created_at DESC)`, `(post_channel_msg_id)`.

**Не храним в БД:** очередь задач и rate-limit-счётчики (Redis, TTL), кэш (потом).

### 1.4 Реализация state machine

Один класс `core/state_machine/account.py` → `AccountStateMachine.transition(account_id, event, initiator, meta=None)`.
Внутри: загрузить Account, проверить переход по таблице, применить побочные эффекты, всё в одной транзакции + запись в `account_status_history`, публикация события в Redis pub/sub. Никто вне state machine не пишет в `accounts.status`.

### 1.5 Справочник фингерпринтов

`worker/fingerprint/device_pool.json` — статичный справочник из 20–30 согласованных связок по всем платформам:

```json
[{"platform": "android", "device_model": "Samsung SM-S928B", "system_version": "SDK 34", "app_version": "10.14.5 (5218)"},
 {"platform": "ios", "device_model": "iPhone15,3", "system_version": "17.5.1", "app_version": "10.14.5"},
 {"platform": "desktop", "device_model": "PC 64bit", "system_version": "Windows 11", "app_version": "5.3.2 x64"}]
```

Правила: только реально существующие модели и актуальные версии Telegram под платформу; нет подозрительных комбинаций (iPhone + Android SDK). Обновляется вручную раз в квартал, автосборщика нет.

`FingerprintGenerator`: при создании аккаунта берёт неиспользованную в пуле связку случайно, дополняет `lang_code`/`system_lang_code` по `proxy.geo`, сохраняет в `accounts.*`. Иммутабельность контролирует сервис (репозиторий отказывается обновлять эти поля, если аккаунт не в `created`).

---

## Этап 2. Очередь задач (Redis + arq)

Обёртка `core/queue/tasks.py` — класс `TaskQueue` с `enqueue(task_name, *args, **kwargs)` и `schedule(task_name, run_at, *args, **kwargs)`. Бизнес-код не зависит от arq напрямую — только от TaskQueue.

Все задачи регистрируются в одном `WorkerSettings.functions`. Одна очередь `arq:queue`.
Ретраи: `max_tries=3` для большинства; `FloodWaitError` = отложенный ретрай на `wait_seconds` (не считается ошибкой). Финально упавшие — arq dead-letter, на старте достаточно.

Типы задач (полный список):

**Shared:** `account.login_start(account_id)`, `account.login_confirm(account_id, code)`, `account.login_password(account_id, password)`, `account.start_warming(account_id)`, `warming.tick(account_id)` (одно действие прогрева, рекуррентная), `warming.maintenance_scheduler()` (cron, каждые N минут выбирает аккаунты из `pool`, планирует `warming.tick` с джиттером), `health.check_proxies()` (cron, раз в 10 минут), `health.cooldown_return()` (cron, каждую минуту), `account.retire(account_id)`, `account.acknowledge_ban(account_id)`.

**Модуль commenting:** `commenting.on_new_post(campaign_id, channel_msg_id)`, `commenting.post_comment(campaign_id, account_id, text, in_reply_to)` (отдельная задача, проходит governor с задержкой).

---

## Этап 3. Worker: фундамент аккаунтов

### 3.1 client_pool (`worker/client_pool/`)

Единственный владелец TelegramClient. Клиент создаётся из сохранённых полей аккаунта:
`TelegramClient(session, api_id, api_hash, device_model=..., system_version=..., app_version=..., lang_code=..., system_lang_code=..., proxy=...)` — НЕ дефолты Telethon. Прокси из БД привязанного `proxy_id`. Клиенты долгоживущие, один event loop, корректный dispose. `.session` не открывается конкурентно из двух процессов.

### 3.2 Логин-флоу (`worker/login/`) — целиком в воркере

Флоу: `login_start` → состояние `waiting_code` → пользователь вводит код в Mini App → `login_confirm` → при 2FA `waiting_password` → `login_password` → успех/ошибка. Состояния пишутся в БД, события публикуются в Redis pub/sub (API опрашивает/subscribe и обновляет UI). Флудвейты при входе = выдержка с ретраем, не долбёжка. После успеха: сессия шифруется и сохраняется, статус через state machine (`created → warming` через `account.start_warming`).

### 3.3 Почему аккаунты умирают (контекст для прогрева и health)

Номер (дешёвые VOIP/ранее баненые — причина №1 мгновенных банов), первый логин через library с датацентр-IP, одинаковые фингерпринты у кластера, общий IP/подсеть (бан кластером), idle-аккаунт подозрительнее активного, ~6 месяцев без логина Telegram сам деактивирует.

---

## Этап 4. API (FastAPI)

Только лёгкие операции. Никакого Telethon. Команды воркеру — через `TaskQueue` (LPUSH), состояние — из Postgres, живые события — pub/sub → SSE/polling в Mini App.

Роутеры (`api/routers/`):
- `accounts.py` — CRUD, пул, список по стадиям, назначение/релиз (через state machine + pub)
- `login.py` — `/login/start`, `/login/confirm`, `/login/password`, эндпоинт статуса логина
- `proxies.py` — CRUD, ручная проверка живости
- `personas.py` — CRUD
- `warming.py` — пресеты, WarmingActivity лента
- `monitoring.py` — дашборд: алерты (неразрешённые health_events), сводка стадий, активные модули, лента активности
- `modules/commenting/*` — кампании CRUD, attach/detach аккаунтов, comment_logs

Авторизация: initData Telegram в `api/deps/`, мидлварь + dev-заглушка.

---

## Этап 5. Прогрев и Health

### 5.1 Прогрев (`worker/warming/`)

- Первичный (`warming`): разовая процедура до готовности. Поддерживающий (в `pool`): непрерывный фон, приостанавливается при `assigned`. Обе пишут в `warming_activities` (kind=initial|maintenance).
- Длительность — недели, не часы; срок настраиваемый.
- Действия с джиттером и окнами активности: подписки на публичные каналы по интересам персоны (постепенно), «чтение» (движение read-статуса истории), редкие реакции/просмотры медиа, `idle_online` (быть онлайн в разумных окнах), редкие правки профиля (не сразу после создания).
- Никаких сообщений незнакомцам на прогреве.
- Критерий готовности `warming → pool` настраиваемый: по сроку и/или числу успешных действий, без флуд-инцидентов за период.

### 5.2 Пресеты интенсивности (`warming_profile`)

- `minimal` — онлайн раз в несколько дней, редкие чтения. Против деактивации.
- `medium` (default) — раз в день короткая человекоподобная сессия: пара просмотров, редкая реакция, случайное окно онлайн. «Тихий читатель».
- `dense` — несколько заходов в день, подписки, взаимодействия. Больше защиты, больше поверхности для антифрода.
- Смена пресета — в любой стадии из Mini App, применяется только пока аккаунт в `pool`.

### 5.3 Health-монитор и governor (`worker/health/`)

HealthEvent (flood_wait, spam_block, restricted, proxy_down, session_revoked, auth_failed) → запись в `health_events` + автоматический переход по стадиям через state machine (обычно `health.incident` → `cooldown` с `previous_status` и `cooldown_until`). `health.cooldown_return` (cron каждую минуту) возвращает истёкшие в previous_status.
Governor: глобальные и на-аккаунт лимиты действий в час/сутки с джиттером, счётчики в Redis с TTL. Каждое исходящее действие — через governor. Это главная защита от флудвейтов.
Алерты в Mini App (pub/sub). Проверка прокси: `health.check_proxies` cron раз в 10 минут, ручная проверка из UI.

---

## Этап 6. Модуль commenting

### 6.1 Правила

- Контейнер модуля = кампания (`commenting.campaigns`).
- Attach: аккаунт должен быть в `pool` (не cooldown) → `container.attach` через state machine → запись в `campaign_accounts` в одной транзакции. UNIQUE account_id = эксклюзивность внутри модуля.
- Detach: `container.detach`, удаление из `campaign_accounts`.
- `override_prompt` у связки кампания-аккаунт заменяет `base_system_prompt`.

### 6.2 Поток нового поста

Слушатель NewMessage в группе обсуждений → `commenting.on_new_post` → аккаунты кампании (status=assigned, окно активности, лимиты governor'а ок) → сбор контекста треда → LLM-генерация (провайдер кампании) → style randomizer → постинг через governor с задержкой из `posting_delay_range` → `comment_logs` (status=posted/failed/flagged, in_reply_to для симуляции диалога между персонами и опционально с реальными комментаторами).

### 6.3 LLM и стиль

- Адаптеры в `worker/llm/` (shared — пригодится parser'у): DeepSeek (OpenAI-совместимый), Gemini. Ключи из конфига.
- Style randomizer (пост-обработка): варьирование длины, эмодзи, опечаток, тона по персоне. Паттерн генерации не должен быть «слишком ровным».

---

## Этап 7. Frontend (React Mini App)

Навбар: 4 таба.

1. **Главная** — алерты (cooldown/banned/proxy_down), сводка стадий аккаунтов (bar), активные модули и их контейнеры, лента активности (комментарии, прогрев).
2. **Аккаунты** — список с фильтром по стадии и поиском. Карточка: стадия, здоровье, прокси, фингерпринт (view-only), персона, пресет прогрева, лента WarmingActivity, **таймлайн стадий** (из account_status_history, для разбора инцидентов), кнопки паузы/релиза/назначения.
3. **Задачи** — карточки модулей → экран модуля (список контейнеров, настройки, лог) → экран контейнера (привязанные аккаунты, настройки: промпт/LLM/окна/задержки).
4. **Ещё** — персоны, прокси (пул, проверка живости), общий аудит-лог, настройки (дефолтный пресет пула, окна активности, интеграции LLM).

Экраны логина аккаунта: ввод номера → «код отправлен» → ввод кода → (2FA-пароль) → статус через polling/SSE.

---

## Этап 8. Прод

- docker-compose: api, worker, frontend, postgres, redis; healthchecks; миграции при старте api.
- E2E-сценарий: прокси → аккаунт (мок логина) → прогрев → pool → кампания → attach → имитация поста → комменты в comment_logs.
- Реальный логин — вручную, последним шагом.

---

## Что сознательно НЕ делаем (v2+)

Реестр модулей (появится со вторым модулем parser), dry-run/модерация комментариев, мульти-канал на кампанию, метрики эффективности, A/B тесты, manual override комментов, экспорт сессий, high-priority очередь, метрики/дашборды экспорта.
