# Telegram-Прайминг — Спецификация модуля

> Модуль привлечения условно-бесплатного трафика (УБТ) через инициацию
> системных Push-уведомлений в личных сообщениях целевых пользователей —
> без отправки текста, медиа или ссылок. Точка конверсии — оформленный
> профиль аккаунта (Bio / аватар / Stories / закреплённый канал-переходник).

## Оглавление

1. [Концепция и механика](#1-концепция-и-механика)
2. [Место модуля в проекте](#2-место-модуля-в-проекте)
3. [Архитектура](#3-архитектура)
4. [Структура данных (БД)](#4-структура-данных-бд)
5. [MTProto-триггеры: что именно вызывает Push](#5-mtproto-триггеры)
6. [API-эндпоинты](#6-api-эндпоинты)
7. [Worker: оркестратор и исполнители](#7-worker-оркестратор-и-исполнители)
8. [Парсер и фильтр аудитории](#8-парсер-и-фильтр-аудитории)
9. [Массовое оформление профилей (POC — Points of Conversion)](#9-массовое-оформление-профилей)
10. [Humanizer / Anti-Spam Engine](#10-humanizer--anti-spam-engine)
11. [Безопасность, прогрев, лимиты](#11-безопасность-прогрев-лимиты)
12. [Frontend / UI-UX](#12-frontend--ui-ux)
13. [Метрики, статистика, логи](#13-метрики-статистика-логи)
14. [Этапы разработки (Roadmap)](#14-этапы-разработки-roadmap)
15. [Открытые вопросы / риски](#15-открытые-вопросы--риски)

---

## 1. Концепция и механика

### 1.1 Что видит целевой пользователь

1. **Push от Telegram** о служебном действии в личке (например «X включил
   автоудаление сообщений» / «X запретил копирование сообщений»).
2. **Триггер любопытства** — открывает диалог узнать «кто это».
3. **Обход анти-спама** — в чате нет ни сообщений, ни ссылок, поэтому
   алгоритмы Telegram не классифицируют событие как рассылку.
4. **Конверсия** — идёт в профиль инициатора; там уже Bio + аватар +
   Stories + закреплённый канал-переходник с оффером.

### 1.2 Чем это отличается от Масстегинга/Шиллинга/ЛС-рассылок

| Модуль | Точка контакта | Носитель оффера | Anti-Spam риск |
|---|---|---|---|
| ЛС-рассылка | Текст в личке | Само сообщение | Максимальный |
| Масстегинг (stories) | Тег в сторис | Сторис + профиль | Средний, нужен Premium для перехода |
| Нейрокомментинг | Коммент в чате | Профиль автора | Средний |
| **Прайминг** | **Push-уведомление** | **Только профиль** | **Низкий (в чате пусто)** |

### 1.3 Ключевые принципы

- **В личке цели не остаётся артефактов** — никаких сообщений, никаких
  ссылок, только служебное системное событие.
- **Оффер живёт в профиле** — Bio, аватар, Stories, закреплённый канал.
- **Аккаунт — расходник** (см. общий инвариант проекта); стратегия
  прогрева и лимитов та же, что для комментинга/шиллинга.
- **Никакого копирования конкурента** — UI и структура задач свои.
  Референс из ТЗ используется как отправная точка, а не как эталон.

---

## 2. Место модуля в проекте

- Пакет: `modules/priming/` — по образцу `modules/shilling/`.
- Схема БД: отдельная PostgreSQL-схема `priming`.
- Router: `/modules/priming/*` (регистрируется в `api/routing.py`).
- Worker: задачи оркестратора и исполнителя в `worker/tasks/priming.py` +
  собственный пакет `modules/priming/worker/`.
- Frontend: `frontend/src/modules/priming/` (по паттерну `commenting/`,
  `shilling/`), пункт бокового меню «Прайминг» с собственной иконкой.
- Аккаунты берутся из общего пула через `AccountStateMachine`
  (инвариант №5). Модуль **не** создаёт свои .session-файлы.
- Профили-оформление, парсер и humanizer — переиспользуют существующие
  или расширяют текущие подсистемы `worker/profiles/`, `worker/warming/`,
  `worker/security/` (см. §9–§10).

### 2.1 Что модуль НЕ делает

- Не пишет сообщений в личку цели.
- Не постит истории у цели — только у собственных аккаунтов (для POC).
- Не занимается прямой покупкой Premium / номеров — это соседние блоки.
- Не хранит контент оффера как переменную — оффер живёт на самом
  аккаунте (в профиле), задача только раздаёт «клики» на этот профиль.

---

## 3. Архитектура

```
modules/priming/
├── __init__.py
├── api/
│   ├── router.py           # /modules/priming/*
│   ├── service.py          # валидация, DTO, оркестрация запуска
│   └── deps.py
├── models/
│   ├── campaign.py         # PrimingCampaign
│   ├── campaign_account.py # аккаунт ↔ кампания (роль: driver)
│   ├── campaign_target.py  # цели (username / phone / user_id / source)
│   ├── target_source.py    # источник целей (chat_id, тип парсера)
│   ├── profile_preset.py   # шаблон оформления профиля (POC)
│   ├── anchor_channel.py   # закреплённый канал-переходник
│   ├── execution_log.py    # per-target log
│   ├── flood_incident.py   # FLOOD_WAIT / privacy / userNotFound
│   └── blacklist.py        # мировой + кампанийный блэклист целей
├── repositories/           # по одному на модель
├── schemas/
│   ├── campaign.py         # Create/Read/Update Pydantic
│   ├── target.py
│   ├── profile_preset.py
│   ├── parser.py           # запросы к парсеру
│   ├── stats.py            # агрегаты для UI
│   └── enums.py            # PrimingMode, TriggerAction, HumanizerMode
├── worker/
│   ├── orchestrator.py     # раскладка целей → аккаунты, темпоритм
│   ├── executor.py         # исполняет 1 прайм на 1 цель
│   ├── trigger.py          # обёртка над MTProto-командами (§5)
│   ├── humanizer.py        # фоновая имитация активности
│   └── registry.py         # регистрация задач в arq
├── parser/
│   ├── chat_messages.py    # активные в чате за N дней
│   ├── chat_members.py     # участники + фильтр «был недавно»
│   └── filters.py          # username / premium / bot / deleted
└── profile_setup/
    ├── anchor_channel.py   # создать/прикрепить mini-канал
    ├── stories.py          # загрузка сторис
    ├── bio.py              # запись Bio/имени/аватара
    └── presets.py          # применение PrimingProfilePreset к аккаунту
```

Общие правила проекта, которые модуль наследует без исключений:

- Только Worker открывает `.session` (инвариант №1).
- API ↔ Worker — только через Redis (инвариант №2).
- Все Telegram-действия проходят через rate-limit governor (инвариант №7).
- Модуль зависит от Core, не наоборот (инвариант №9).
- Мягкое удаление не используется (инвариант №10).

---

## 4. Структура данных (БД)

Все таблицы в схеме `priming.*`. Ниже — минимально необходимый набор.

### 4.1 `priming.campaigns`

| Поле | Тип | Описание |
|---|---|---|
| `id` | BIGINT PK | |
| `name` | VARCHAR(120) | |
| `status` | ENUM(`draft`, `queued`, `running`, `paused`, `stopped`, `finished`, `failed`) | |
| `mode` | ENUM(`priming`) | Зарезервировано под мульти-режим (stories/priming). |
| `trigger_action` | ENUM (см. §5) | Какое именно системное событие вызываем. |
| `humanizer_mode` | ENUM(`off`, `balanced`, `aggressive`) | |
| `delay_between_targets_sec_min` | INT | |
| `delay_between_targets_sec_max` | INT | |
| `flood_wait_pause_sec` | INT | по умолчанию 500 |
| `max_flood_waits_per_account` | INT | по умолчанию 3 |
| `daily_limit_per_account` | INT | 35–40 — по умолчанию из режима |
| `warmup_profile` | ENUM(`cold`, `warm`, `hot`) | подставляет пары `limit / delay` |
| `require_username` | BOOL | |
| `premium_only` | BOOL | |
| `exclude_bots` | BOOL | true |
| `exclude_deleted` | BOOL | true |
| `exclude_admins` | BOOL | true |
| `stop_on_privacy_rate` | FLOAT | стоп при доле USER_PRIVACY_RESTRICTED > X |
| `created_by` | BIGINT | user_id |
| `created_at` / `updated_at` | TIMESTAMPTZ | |
| `started_at` / `finished_at` | TIMESTAMPTZ NULL | |

### 4.2 `priming.campaign_accounts`

Связка «кампания ↔ аккаунт-инициатор». Каждый аккаунт — driver прайминга.

| Поле | Тип |
|---|---|
| `id` | BIGINT PK |
| `campaign_id` → `campaigns.id` | FK |
| `account_id` → `accounts.id` | FK |
| `state` | ENUM(`idle`, `working`, `cooldown`, `quarantined`, `disabled`) |
| `flood_waits_consecutive` | INT |
| `flood_waits_total` | INT |
| `primes_today` | INT |
| `primes_total` | INT |
| `last_prime_at` | TIMESTAMPTZ NULL |
| `next_available_at` | TIMESTAMPTZ NULL |
| `profile_preset_id` | FK NULL |

UNIQUE(`campaign_id`, `account_id`).

### 4.3 `priming.campaign_targets`

Одна строка = одна цель кампании.

| Поле | Тип |
|---|---|
| `id` | BIGINT PK |
| `campaign_id` | FK |
| `source_id` | FK → `target_sources.id` NULL |
| `tg_user_id` | BIGINT NULL |
| `username` | VARCHAR NULL |
| `phone` | VARCHAR NULL |
| `has_premium` | BOOL NULL |
| `last_seen_bucket` | ENUM(`recently`, `within_week`, `within_month`, `long_ago`, `unknown`) |
| `status` | ENUM(`pending`, `assigned`, `primed`, `failed`, `skipped`, `blacklisted`) |
| `assigned_account_id` | FK NULL |
| `attempts` | INT |
| `last_error_code` | VARCHAR NULL |
| `primed_at` | TIMESTAMPTZ NULL |

Партицирование: по `campaign_id` (для больших кампаний, опционально).

### 4.4 `priming.target_sources`

Источники, из которых собран пул целей.

| Поле | Тип |
|---|---|
| `id` | BIGINT PK |
| `campaign_id` | FK |
| `kind` | ENUM(`chat_messages`, `chat_members`, `manual_list`, `upload_csv`) |
| `chat_ref` | VARCHAR NULL | @username / invite / chat_id |
| `days_window` | INT NULL |
| `min_messages` | INT NULL |
| `raw_count` | INT |
| `after_filters_count` | INT |
| `parsed_at` | TIMESTAMPTZ |

### 4.5 `priming.profile_presets`

Шаблон оформления профиля-конверсии.

| Поле | Тип |
|---|---|
| `id` | BIGINT PK |
| `owner_user_id` | BIGINT |
| `name` | VARCHAR |
| `first_name_pool` | JSONB (list) |
| `last_name_pool` | JSONB |
| `username_generator` | ENUM(`llm`, `dict`, `template`) |
| `bio_text` | TEXT |
| `bio_link` | VARCHAR NULL |
| `avatar_source` | ENUM(`upload`, `service_gallery`) |
| `stories_pool_id` | FK NULL |
| `anchor_channel_template_id` | FK NULL |

### 4.6 `priming.anchor_channels`

Мини-канал, который прикрепляется в шапку профиля.

| Поле | Тип |
|---|---|
| `id` | BIGINT PK |
| `account_id` | FK |
| `channel_tg_id` | BIGINT |
| `title` | VARCHAR |
| `is_public` | BOOL |
| `pinned_post_id` | BIGINT NULL |
| `pinned_post_text` | TEXT |
| `attached_to_profile_at` | TIMESTAMPTZ |
| `state` | ENUM(`ok`, `broken`, `reset_required`) |

### 4.7 `priming.execution_log`

Один прайм — одна запись (append-only).

| Поле | Тип |
|---|---|
| `id` | BIGINT PK |
| `campaign_id`, `account_id`, `target_id` | FK |
| `started_at`, `finished_at` | TIMESTAMPTZ |
| `outcome` | ENUM(`primed`, `flood_wait`, `privacy_restricted`, `deleted`, `not_found`, `channel_pinned_error`, `internal_error`) |
| `error_code` | VARCHAR NULL |
| `flood_wait_sec` | INT NULL |
| `trigger_action` | ENUM |
| `latency_ms` | INT |

### 4.8 `priming.flood_incidents`

Отдельный агрегированный лог по флудвейтам per-account.

| Поле | Тип |
|---|---|
| `id`, `campaign_account_id`, `at`, `flood_wait_sec`, `endpoint` | — |

### 4.9 `priming.blacklist`

- Владелец: `owner_user_id` или NULL (глобальный).
- Ключи: `tg_user_id` / `username` / `phone`.
- Причина: `manual`, `privacy_restricted`, `already_primed_N_days`,
  `bot`, `deleted`, `complaint`.

---

## 5. MTProto-триггеры

Прайминг «дёргает» служебные события Telegram, которые генерируют
push-уведомления у цели, но НЕ создают сообщений в чате. Хранится список
поддерживаемых `trigger_action`; для каждого фиксируем MTProto-вызов и
известные ограничения. Точный набор действий уточняется на этапе R&D
(см. §14, этап 1).

Кандидаты (реализуем поэтапно, начать с 1–2):

| `trigger_action` | MTProto call | Push у цели | Ограничения |
|---|---|---|---|
| `set_ttl_1d` / `set_ttl_off` | `messages.SetHistoryTTL` (в лички цели) | «X включил автоудаление» | Работает в существующем диалоге; для «пустой» лички нужен предварительный служебный контакт. |
| `set_content_protection` | `messages.SetHistoryTTL` + `messages.ToggleNoForwards` (если применимо к личке) | «X запретил копирование» | Может быть заблокировано на уровне лички у обычных user↔user. |
| `secret_chat_request` | `messages.RequestEncryption` | «X отправил приглашение в секретный чат» | Наименее рискованный кандидат, есть отдельный push. |
| `contact_added` | `contacts.AddContact` с `add_phone_privacy_exception` | «X добавил вас в контакты» | Требует username/phone и не гарантирует push у всех клиентов. |
| `pinned_message_ping` | Закрепление своего же служебного сообщения в личке | Условно рабочий вариант | Часть клиентов не показывает push. |

Требования к обёртке `worker/priming/trigger.py`:

- Единый интерфейс `run(action, target) -> TriggerResult`.
- Обработка `FLOOD_WAIT_X` → `TriggerResult(outcome=flood_wait, wait=X)`.
- Обработка `USER_PRIVACY_RESTRICTED`, `USER_DEACTIVATED`,
  `PEER_ID_INVALID`, `USERNAME_NOT_OCCUPIED` → пометить цель `skipped/blacklisted`.
- Все вызовы обёрнуты в rate-limit governor (инвариант №7).
- Идемпотентность: перед вызовом действия читаем текущее состояние
  и не «включаем уже включённое» без нужды (уменьшает шум для анти-фрода).

---

## 6. API-эндпоинты

Prefix `/modules/priming`. Все — под теми же авторизациями, что и
существующие модули.

Кампании

- `POST   /campaigns` — создать (draft).
- `GET    /campaigns` — список (paginated, filter by status).
- `GET    /campaigns/{id}` — детально.
- `PATCH  /campaigns/{id}` — редактировать (только в `draft`/`paused`).
- `POST   /campaigns/{id}/start` — валидация + постановка в очередь.
- `POST   /campaigns/{id}/pause`.
- `POST   /campaigns/{id}/resume`.
- `POST   /campaigns/{id}/stop`.
- `DELETE /campaigns/{id}` — только `draft`/`finished`/`failed`.

Аккаунты в кампании

- `GET    /campaigns/{id}/accounts` — состояние, лимиты, next_available_at.
- `POST   /campaigns/{id}/accounts` — прикрепить (массово, из пула).
- `DELETE /campaigns/{id}/accounts/{account_id}` — отключить.
- `POST   /campaigns/{id}/accounts/{account_id}/quarantine` — вручную.

Цели

- `POST   /campaigns/{id}/targets/import` — CSV / текст / ручной список.
- `POST   /campaigns/{id}/targets/parse` — запустить парсер (см. §8),
  возвращает `job_id`.
- `GET    /campaigns/{id}/targets` — с фильтрами (status, source).
- `POST   /campaigns/{id}/targets/blacklist` — массово.

Профили и оформление

- `GET    /profile-presets` / `POST` / `PATCH` / `DELETE`.
- `POST   /accounts/{account_id}/apply-preset` — применить preset,
  возвращает `job_id`.
- `POST   /accounts/{account_id}/anchor-channel` — создать/переустановить.

Статистика

- `GET    /campaigns/{id}/stats` — агрегаты (см. §13).
- `GET    /campaigns/{id}/logs` — постранично, фильтры по outcome.
- `WS     /campaigns/{id}/live` — стрим логов и счётчиков (SSE/WS).

Служебное

- `GET    /trigger-actions` — какие `trigger_action` включены в билде и их
  описание для UI.

---

## 7. Worker: оркестратор и исполнители

### 7.1 Задачи arq

- `priming.orchestrator_tick(campaign_id)` — каждые N секунд:
  1. Проверяет статус кампании, лимиты аккаунтов, календарь.
  2. Отбирает следующую партию `(target, account)` пар.
  3. Публикует `priming.execute_prime(target_id, account_id, action)`.
  4. Планирует следующий tick с учётом джиттера и humanizer_mode.

- `priming.execute_prime(target_id, account_id, action)` — одна
  единица работы:
  1. Резервирует аккаунт через AccountStateMachine.
  2. Через `TelegramClient` открывает peer цели.
  3. Выполняет `trigger.run(action, target)`.
  4. Логирует в `execution_log` + инкрементит счётчики.
  5. При `FLOOD_WAIT_X` — увеличивает `flood_waits_consecutive`,
     ставит `next_available_at`, при переборе — `quarantined`.
  6. Освобождает аккаунт.

- `priming.humanizer_beat(account_id)` — фоновая имитация активности
  между праймами (см. §10).

- `priming.parser_run(source_id)` — парсер (см. §8).

- `priming.profile_apply(account_id, preset_id)` — оформление профиля
  (см. §9).

### 7.2 Правила темпоритма

- Между двумя праймами с одного аккаунта — рандом
  `[delay_min .. delay_max]` + джиттер ±20%.
- Между праймами одного аккаунта в разные цели — не больше
  `daily_limit_per_account` в сутки (сбрасывается по UTC-дню или локали
  аккаунта, TBD).
- При получении `FLOOD_WAIT_X`:
  - Аккаунт → `cooldown` на `max(X, flood_wait_pause_sec)`.
  - При превышении `max_flood_waits_per_account` подряд — `quarantined`,
    кампания получает событие и продолжает без него.
- Кампания автоматически ставится на паузу при
  `stop_on_privacy_rate` за 200 последних попыток.

### 7.3 Идемпотентность и рестарты

- Каждая пара `(campaign_id, target_id)` праймится не чаще, чем раз в
  N дней (`already_primed_N_days`, конфиг).
- `execute_prime` — идемпотентен по `(target_id, campaign_id)` через
  advisory-lock, чтобы после рестарта worker'а не задвоить.

---

## 8. Парсер и фильтр аудитории

### 8.1 Источники

1. **Chat messages** — аккаунт вступает (или уже участник) в целевой
   чат/канал-обсуждение, читает историю за `days_window` дней, собирает
   `sender_id` c `min_messages` сообщениями. Ротация аккаунта-парсера,
   не работать с одного и того же.
2. **Chat members** — `channels.GetParticipants` c пагинацией. Фильтр
   `last_seen_bucket = recently` через `user.status`.
3. **Manual list** — пользовательский ввод (username, phone, id).
4. **CSV upload** — тот же формат, из файла.

### 8.2 Фильтры

- `require_username` (по умолчанию on).
- `premium_only` (`user.premium == true`).
- `exclude_bots` / `exclude_deleted` (`user.deleted`, `user.bot`).
- `exclude_admins` — по данным чата.
- Дедуп по `tg_user_id` в рамках кампании и глобального blacklist.
- Опция: `min_account_age` — оценка по id (эвристика, не гарантирована).

### 8.3 Storage

- Найденные цели сначала складываются в `priming.campaign_targets` со
  статусом `pending`, отчёт (сколько отфильтровано, сколько добавлено)
  идёт в `target_sources`.
- Парсер сам НЕ заводит `campaign_accounts` — работает через свои
  «читающие» аккаунты из пула, отбираемые state machine.

---

## 9. Массовое оформление профилей

Точка конверсии — сам аккаунт. Модуль включает подсистему подготовки
профилей, применимую и к другим модулям (комментинг/шиллинг тоже
выигрывают от «живого» профиля).

### 9.1 Компоненты preset

- **Имя/фамилия** — из пула, поддерживаем локали ru/uk/en.
- **Username** — генерация через LLM (уже есть `worker/llm/`) или
  словарные шаблоны; проверка занятости (`account.CheckUsername`).
- **Аватар** — из локальной папки/галереи сервиса; фильтр «одинаковые
  фото на разных аккаунтах» — запрет по `phash`.
- **Bio** — текстовый шаблон + опциональная короткая ссылка.
- **Stories pool** — ротация из загруженных медиа.
- **Anchor channel** — по шаблону: заголовок, аватар канала, тело
  закреплённого поста, публичный/приватный, ссылка-приглашение.

### 9.2 Способы размещения оффера

1. **Anchor Channel** — комбайн создаёт персональный канал под каждым
   аккаунтом, публикует пост, закрепляет, добавляет канал в шапку
   профиля (`channels.EditPersonalChannel`, RPC при наличии).
2. **Stories** — публикация с оффером и ссылкой-стикером.
3. **Bio** — короткая фраза + ссылка (t.me/bot?start=…).

Все три способа комбинируются: preset задаёт, какие включены.

### 9.3 Job `profile_apply`

Пошагово, каждый шаг идемпотентен и логируется:

1. Установить имя/фамилию/аватар.
2. Установить username (с ретраями при коллизии).
3. Установить bio.
4. Опубликовать сторис (если preset так задан).
5. Создать/использовать anchor-канал и закрепить его в шапке.

При ошибке шага — retry с backoff; при потере аккаунта — очистка
`anchor_channel` в состояние `reset_required` (чтобы не создавать
дубли каналов при следующем применении preset'а).

---

## 10. Humanizer / Anti-Spam Engine

Между праймами каждый аккаунт-инициатор ведёт себя как обычный юзер:

- Читает 1–3 поста в публичных каналах (список каналов — пул проекта).
- Иногда ставит эмодзи-реакцию (не всегда, случайный подбор).
- Иногда открывает stories чужих каналов.
- В `aggressive`-режиме — заходит в 1–2 чата, кликает по паре
  сообщений (без отправки).

Работает как отдельный arq-job `priming.humanizer_beat`, запускаемый
оркестратором в паузах. Не пересекается с прайминг-задачами по времени,
чтобы не создавать «дребезг» на MTProto.

Правило: humanizer никогда не пишет сообщений незнакомцам — только
пассивные/публичные действия.

---

## 11. Безопасность, прогрев, лимиты

### 11.1 Warm-up pipeline

Наследует общий Account Lifecycle:

- **День 1–3 (cold)**: `daily_limit = 5–6`, `delay = 200..600 сек`.
- **День 4–7 (warm)**: `daily_limit = 15–20`, `delay = 60..200 сек`.
- **День 8+ (hot)**: `daily_limit = 35–40`, `delay = 20..60 сек`.

`warmup_profile` в кампании задаёт стартовые лимиты, но overrides
могут быть заданы явно.

### 11.2 Правила автостопа

- `flood_waits_consecutive >= max_flood_waits_per_account` →
  аккаунт в карантин, событие в health-монитор.
- `USER_PRIVACY_RESTRICTED > stop_on_privacy_rate` на последних 200
  попытках → пауза кампании.
- Массовые `USER_DEACTIVATED` (>N% за окно) → пометить парсер-источник
  «протухшим», предложить перепарсить.

### 11.3 Blacklist

- Глобальный (owner_user_id NULL) — общий для всех кампаний
  пользователя.
- Кампанийный — если цель уже праймилась в этой кампании за последние
  N дней, пропуск.
- Ручные добавления через UI и API.

---

## 12. Frontend / UI-UX

### 12.1 Точки входа

- Новый пункт бокового меню **«Прайминг»** (иконка — «шёпот» / bell-in-shadow;
  выбираем свою, не копируем конкурента).
- Внутри — три экрана-таба: **Кампании / Профили / Аудитория**.

Не копируем расстановку конкурента (общий скролл сверху вниз). Наш
паттерн — трёхколоночный layout на десктопе:

```
┌──────────── Header (название кампании, статус, кнопки run/pause/stop) ────────────┐
│ Left rail          │ Center (main config)            │ Right rail (stats+logs)   │
│ • Аккаунты пула    │ 1. Триггер (Push action)        │ • Live-счётчики           │
│ • Кампании         │ 2. Аудитория (парсер/загрузка)  │ • Активные аккаунты       │
│ • Профили-пресеты  │ 3. Профиль-пресет (POC)         │ • Лента событий           │
│                    │ 4. Темп и лимиты                │ • Ошибки / флудвейты      │
│                    │ 5. Humanizer                    │                           │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

На мобильном — вертикальный аккордеон, порядок тот же.

### 12.2 Экран «Новая кампания» — блоки

1. **Идентификация**: имя, теги.
2. **Триггер** (свой блок, аналога у конкурента нет):
   - Селектор `trigger_action` (радио-группа с иконками; каждая с
     подписью «что увидит цель в пуше»).
   - Live-превью пуш-уведомления (мок под iOS/Android).
3. **Аккаунты**: выбор из пула, фильтры по прогреву, тегам, гео.
4. **Аудитория**:
   - Табы: `Парсер чата`, `Импорт CSV`, `Ручной список`.
   - Для парсера — форма (chat_ref, days_window, min_messages) и
     кнопка «Пропарсить», результат — карточка с raw/after счётчиками
     и кнопкой «Использовать».
   - Фильтры: `require_username`, `premium_only`, `exclude_bots`,
     `exclude_deleted`, `exclude_admins`, `last_seen_bucket`.
5. **Профиль-пресет (POC)**:
   - Селектор pre-existing preset или «Создать новый».
   - Внутри preset: имя/юзернейм/аватар/bio/stories/anchor-channel.
   - Кнопка «Применить preset к N выбранным аккаунтам» — запускает job.
6. **Темп и лимиты**:
   - Слайдер `delay_between_targets` (диапазон min/max).
   - Числа: `daily_limit_per_account`, `flood_wait_pause`,
     `max_flood_waits_per_account`.
   - Селект `warmup_profile` (`cold / warm / hot`) — авто-подставит
     дефолты, оставим возможность override.
7. **Humanizer**: enum + чекбоксы «читать посты / реакции / stories».
8. **Автостоп**: `stop_on_privacy_rate`, ручные ограничения по времени
   (окна активности «10:00–22:00»).

### 12.3 Экран «Профили»

- Каталог preset'ов (карточки с preview).
- Мастер создания preset'а (пошаговый визард, аналог DesignSync UX).
- Кнопка «Применить к аккаунтам» — открывает bulk-панель.
- Экран аккаунта: чек-лист «что настроено» (аватар/имя/юзернейм/bio/
  stories/anchor-channel), кнопки «переустановить».

### 12.4 Экран «Аудитория»

- Общий каталог собранных списков целей (по всем кампаниям
  пользователя).
- Blacklist manager: поиск, массовые операции.

### 12.5 Дизайн-язык (не копируем конкурента)

- Скругления 12–16 px (у конкурента жёсткие 8 px), больше воздуха.
- Панель run/pause/stop — в шапке, не внизу; статус кампании
  индикатором рядом (пульсирующая точка).
- Live-логи — правый rail, не отдельная секция снизу.
- Иконки — outline + мягкая заливка на состоянии hover.
- Тёмная тема первична, светлая — производная (пресет `commenting`).
- Цветовая роль:
  - `primary` — акценты кнопок запуска;
  - `warning` — состояния `cooldown`;
  - `danger` — `quarantined` / `flood_wait`;
  - `success` — `primed`.

Ничего оранжево-неонового «Купить модуль» — оффер-стену переиспользуем
из существующей биллинговой заглушки (см. `frontend/src/modules/…/paywall`).

---

## 13. Метрики, статистика, логи

Основные KPI (на дашборде кампании):

- **Отправлено праймов** — суммарно и в разрезе аккаунтов.
- **Успешность** — `primed / attempts`.
- **Privacy rate** — доля `USER_PRIVACY_RESTRICTED`.
- **Flood rate** — доля `FLOOD_WAIT` от попыток.
- **Аккаунты в карантине** — счётчик.
- **Прогресс** — % от общего пула целей.
- **CTR на профиль** (если удастся снимать через сторонний attribution:
  клики по ссылке в Bio/anchor-канале). В MVP оставить руками.

Логи:

- Real-time stream в правой панели (WS/SSE).
- Полнотекстовый лог доступен через `GET /campaigns/{id}/logs`.
- Экспорт CSV.

---

## 14. Этапы разработки (Roadmap)

Разбиваем на 7 этапов. Каждый этап — самостоятельный PR/набор PR с
работающим срезом функционала. Порядок оптимизирован под ранние
интеграционные тесты MTProto (§5) — самое рискованное сначала.

### Этап 0. R&D по MTProto-триггерам (обязательный до старта)

- Проверить на **тестовых** аккаунтах каждый кандидат из §5:
  - реально ли приходит push у цели;
  - есть ли в чате артефакт (сообщение);
  - какие ошибки Telegram возвращает.
- Задокументировать в `docs/priming-triggers.md` минимум два рабочих
  `trigger_action`.
- Deliverable: `worker/priming/trigger.py` (скелет) + отчёт.

### Этап 1. Каркас модуля и БД

- Пакет `modules/priming/`, роутер, подключение в `api/routing.py`.
- Схема `priming.*`, alembic-миграции для таблиц из §4 (без анкер-канала
  и stories, эти позже).
- Enum'ы, Pydantic-схемы, репозитории.
- Unit-тесты репозиториев.
- Deliverable: пустой UI-стаб на фронте (только пункт меню и «coming soon»),
  API возвращает 200 на `GET /campaigns`.

### Этап 2. Ядро исполнения (single-action MVP)

- `worker/priming/orchestrator.py` + `executor.py` для одного
  `trigger_action` (самый безопасный из §5).
- Rate-limit governor интеграция.
- FLOOD_WAIT / privacy handling → execution_log + flood_incidents.
- Ручной ввод/CSV целей (без парсера).
- Мини-UI: список аккаунтов, ручной список целей, запуск, live-лог.
- E2E-тест на dry-run режиме (без реальных MTProto-вызовов).

### Этап 3. Парсер аудитории

- `modules/priming/parser/` — chat_messages, chat_members, filters.
- Job `priming.parser_run` + прогресс в UI.
- Фильтры и агрегированный отчёт (raw/after).
- Тесты с mock'ом Telethon.

### Этап 4. Оформление профилей (POC)

- `modules/priming/profile_setup/`:
  - имя/аватар/username/bio;
  - stories (upload + publish);
  - anchor-channel (создание, публикация, закрепление в шапке).
- Preset-каталог, UI-визард.
- Bulk-применение preset'а к N аккаунтам.
- Тесты по каждому шагу (mock RPC).

### Этап 5. Humanizer и мульти-action

- `humanizer_beat` — чтение постов, реакции, stories.
- Дополнительные `trigger_action` из §5 (минимум ещё один).
- Ротация действий, чтобы не долбить один и тот же пуш.

### Этап 6. Прогрев, автостоп, health-интеграция

- Warm-up profiles (cold/warm/hot) — авто-подстановка лимитов.
- Автостоп по privacy_rate / flood_rate.
- Интеграция с health-монитором проекта: каждый инцидент — событие в
  общий health-стрим аккаунта.
- Экспорт метрик кампании в общий дашборд.

### Этап 7. Полировка UI, документация, релиз

- Финализация правого rail (live-статистика).
- Blacklist manager.
- Пейволл модуля (переиспользуем существующий).
- Обновление `docs/PROJECT-STAGES.md`, README раздел о модуле.
- Нагрузочный/soak-тест на прогретом пуле (7 дней).

---

## 15. Открытые вопросы / риски

1. **Актуальность MTProto-триггеров.** Telegram может закрыть любую из
   лазеек в §5. Нужен резервный список действий и мониторинг
   «cannot_trigger_push» как отдельный outcome.
2. **Push в «пустой» лички.** Некоторые триггеры (напр. `SetHistoryTTL`)
   требуют существующего диалога с ≥1 сообщением. Возможно, придётся
   слать «системное» сообщение стикером и сразу удалять его — рискованно;
   выносим на R&D этапа 0.
3. **Anchor-канал в шапку профиля.** RPC доступен, но может требовать
   Premium. Проверить и, если так, дать fallback на «ссылка в Bio».
4. **Юридика.** Модуль — серая зона относительно ToS Telegram и в
   некоторых юрисдикциях — рекламного законодательства (спам-рассылка
   без согласия). Держать в UI дисклеймер, как у существующих модулей.
5. **Attribution.** Без sandbox-бота на стороне оффера мы не увидим,
   пришёл ли клик из прайминга. В MVP оставляем счётчики только «наших»
   действий; CTR-мерилка — отдельный трек.
6. **Пересечение с масс-тегингом.** Часть пользователей уже видит нас
   в stories. Нужен режим «не праймить, если уже тегался за N дней».
