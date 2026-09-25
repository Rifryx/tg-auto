# НейроШиллинг — Спецификация модуля

## Оглавление
1. [Концепция](#1-концепция)
2. [Два режима работы](#2-два-режима-работы)
3. [Архитектура модуля](#3-архитектура-модуля)
4. [Структура данных (БД)](#4-структура-данных)
5. [API-эндпоинты](#5-api-эндпоинты)
6. [Worker / Воркер](#6-worker)
7. [LLM-интеграция](#7-llm-интеграция)
8. [Frontend / UI](#8-frontend--ui)
9. [Этапы разработки](#9-этапы-разработки)

---

## 1. Концепция

**НейроШиллинг** — модуль автоматического воспроизведения нативных диалогов
между подконтрольными Telegram-аккаунтами в комментариях/чатах публичных каналов.

**Механика**: несколько аккаунтов разыгрывают заранее подготовленный сценарий
переписки (вопрос → ответ → рекомендация). В текст нативно вплетается
упоминание бренда/продукта/канала. Прямые ссылки и @username НЕ используются —
только текстовое название бренда.

**Отличие от НейроКомментинга**: комментинг = один аккаунт пишет независимый
комментарий к посту. Шиллинг = координированный диалог 2–10+ аккаунтов под
постом, имитирующий живое обсуждение.

---

## 2. Два режима работы

### 2.1 Режим «Кампания» (Продвижение)
Цель: продвижение бренда/продукта в ЧУЖИХ чатах/каналах.

- Сценарий с ролями (Инициатор, Ответчик, Скептик и т.д.)
- Фиксированный набор реплик (с возможностью ИИ-рерайтинга)
- Таргетинг: список целевых каналов/чатов (ручной ввод ссылок)
- Каждый канал обрабатывается последовательно с кулдауном
- Лимит постов на канал (рекомендуется 1 для незаметности)

### 2.2 Режим «Оживление чата» (Chat Revival)
Цель: поддержание активности в СВОЁМ чате/группе.

- Без фиксированного сценария — ИИ генерирует тематические обсуждения
- Пользователь задаёт тематику, тон, интенсивность
- Аккаунты ведут непрерывный тематический диалог
- Цикличная работа: генерация новых тем → обсуждение → пауза → повтор

---

## 3. Архитектура модуля

Модуль следует паттерну `modules/commenting/` — самостоятельный пакет
со своей структурой:

```
modules/shilling/
├── __init__.py
├── api/
│   ├── __init__.py
│   ├── router.py          # FastAPI роутер, prefix=/modules/shilling
│   └── service.py         # Бизнес-логика (валидация, failover)
├── models/
│   ├── __init__.py
│   ├── campaign.py         # ShillingCampaign ORM
│   ├── scenario.py         # ShillingScenario + ScenarioStep ORM
│   ├── campaign_account.py # ShillingCampaignAccount (аккаунт → роль)
│   ├── campaign_target.py  # ShillingTarget (целевые каналы)
│   ├── execution_log.py    # ShillingExecutionLog
│   └── blacklist.py        # ShillingBlacklist
├── repositories/
│   ├── __init__.py
│   ├── campaign.py
│   ├── scenario.py
│   ├── campaign_account.py
│   ├── campaign_target.py
│   ├── execution_log.py
│   └── blacklist.py
├── schemas/
│   ├── __init__.py
│   ├── campaign.py         # Pydantic Create/Read/Update
│   ├── scenario.py
│   ├── campaign_account.py
│   ├── campaign_target.py
│   ├── execution_log.py
│   ├── blacklist.py
│   └── stats.py            # Агрегаты для UI
├── worker/
│   ├── __init__.py
│   ├── orchestrator.py     # Основной оркестратор диалога
│   ├── executor.py         # Отправка отдельных реплик
│   ├── revival.py          # Логика режима «Оживление чата»
│   └── registry.py         # Регистрация задач в arq
└── llm/
    ├── __init__.py
    ├── rewriter.py         # Рерайтинг реплик под контекст
    └── revival_generator.py # Генерация тем и реплик для оживления
```

**DB-схема**: отдельная PostgreSQL-схема `shilling` (по аналогии с `commenting`).

---

## 4. Структура данных

### 4.1 `shilling.campaigns` — Кампания

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | BIGINT PK | |
| `name` | VARCHAR | Название кампании |
| `mode` | VARCHAR | `promotion` / `revival` |
| `brand_name` | VARCHAR NULL | Бренд/ключевая фраза (для promotion) |
| `brand_link` | VARCHAR NULL | Ссылка бренда (опционально, для контекста LLM) |
| `topic` | TEXT NULL | Тема обсуждения (для revival) |
| `llm_provider` | VARCHAR | `deepseek` / `gemini` |
| `unique_messages` | BOOL | Тумблер: ИИ рерайтит реплики для каждого канала |
| `use_chat_context` | BOOL | Тумблер: ИИ учитывает контекст поста/чата |
| `reply_delay_min_sec` | INT | Мин. пауза между репликами внутри диалога |
| `reply_delay_max_sec` | INT | Макс. пауза между репликами |
| `target_delay_min_sec` | INT | Мин. пауза между целями (каналами) |
| `target_delay_max_sec` | INT | Макс. пауза между целями |
| `posts_per_target` | INT | Лимит постов на канал за запуск (дефолт 1) |
| `scenario_id` | BIGINT FK NULL | Привязанный сценарий |
| `auto_responder` | VARCHAR | `off` / `neuro_dialogs` / `reply_in_chat` |
| `reserve_enabled` | BOOL | Тумблер: резервные аккаунты при бане |
| `msg_limit_per_hour` | INT NULL | Лимит сообщений/час на аккаунт |
| `msg_limit_total` | INT NULL | Лимит всего сообщений на аккаунт |
| `media_asset_id` | BIGINT FK NULL | Прикреплённое медиа к репликам |
| `enabled` | BOOL | Активна ли кампания |
| `status` | VARCHAR | `draft` / `ready` / `running` / `paused` / `completed` / `error` |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

### 4.2 `shilling.scenarios` — Сценарий

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | BIGINT PK | |
| `campaign_id` | BIGINT FK | |
| `name` | VARCHAR | Название (опционально, для сохранённых) |
| `is_template` | BOOL | Сохранённый шаблон (можно переиспользовать) |
| `persons_count` | INT | Кол-во персон в сценарии |
| `ai_generated` | BOOL | Сгенерирован ли ИИ |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

### 4.3 `shilling.scenario_roles` — Роли в сценарии

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | BIGINT PK | |
| `scenario_id` | BIGINT FK | |
| `name` | VARCHAR | Название роли: «Инициатор», «Скептик» и т.д. |
| `character` | TEXT NULL | Описание характера/стиля речи |
| `color` | VARCHAR NULL | Цвет для UI |
| `sort_order` | INT | Порядок отображения |

### 4.4 `shilling.scenario_steps` — Шаги диалога (реплики)

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | BIGINT PK | |
| `scenario_id` | BIGINT FK | |
| `role_id` | BIGINT FK | Роль, которая говорит |
| `step_order` | INT | Порядковый номер шага |
| `step_type` | VARCHAR | `message` / `reaction` |
| `text` | TEXT NULL | Текст реплики (NULL для reaction) |
| `reply_to_step_id` | BIGINT FK NULL | На какой шаг отвечает (reply) |
| `delay_before_sec` | INT NULL | Индивидуальная задержка перед шагом |
| `reaction_emoji` | VARCHAR NULL | Эмодзи для типа reaction |

### 4.5 `shilling.campaign_accounts` — Аккаунты кампании

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | BIGINT PK | |
| `campaign_id` | BIGINT FK | |
| `account_id` | BIGINT FK | Ссылка на `accounts.id` |
| `role_id` | BIGINT FK NULL | Привязанная роль в сценарии |
| `is_reserve` | BOOL | Резервный аккаунт |
| `created_at` | TIMESTAMPTZ | |

### 4.6 `shilling.campaign_targets` — Целевые каналы

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | BIGINT PK | |
| `campaign_id` | BIGINT FK | |
| `raw_input` | VARCHAR | Введённая ссылка (@username, t.me/...) |
| `kind` | VARCHAR | `username` / `invite` / `chat_id` |
| `resolved_chat_id` | BIGINT NULL | Резолвнутый chat_id |
| `title` | VARCHAR NULL | Название канала (заполняется при резолве) |
| `status` | VARCHAR | `pending` / `resolved` / `error` |
| `last_error` | TEXT NULL | |
| `created_at` | TIMESTAMPTZ | |

### 4.7 `shilling.execution_logs` — Лог выполнения

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | BIGINT PK | |
| `campaign_id` | BIGINT FK | |
| `target_id` | BIGINT FK | Целевой канал |
| `account_id` | BIGINT FK | Аккаунт отправивший |
| `role_id` | BIGINT FK NULL | Роль аккаунта |
| `step_id` | BIGINT FK NULL | Шаг сценария |
| `message_text` | TEXT | Отправленный текст |
| `posted_message_id` | BIGINT NULL | ID сообщения в Telegram |
| `status` | VARCHAR | `sent` / `failed` / `skipped` / `replaced` |
| `error` | TEXT NULL | |
| `created_at` | TIMESTAMPTZ | |

### 4.8 `shilling.blacklist` — Чёрный список

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | BIGINT PK | |
| `campaign_id` | BIGINT FK | |
| `chat_id` | BIGINT NULL | |
| `username` | VARCHAR NULL | |
| `reason` | TEXT NULL | |
| `auto` | BOOL | Авто-добавлен при ошибке |
| `created_at` | TIMESTAMPTZ | |

---

## 5. API-эндпоинты

Префикс: `/modules/shilling`

### Кампании
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/campaigns` | Список кампаний |
| POST | `/campaigns` | Создать кампанию |
| GET | `/campaigns/{id}` | Получить кампанию |
| PATCH | `/campaigns/{id}` | Обновить кампанию |
| DELETE | `/campaigns/{id}` | Удалить кампанию |

### Сценарии
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/campaigns/{id}/scenario` | Получить сценарий кампании |
| PUT | `/campaigns/{id}/scenario` | Создать/заменить сценарий |
| POST | `/campaigns/{id}/scenario/generate` | Сгенерировать через ИИ |

### Роли сценария
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/scenarios/{id}/roles` | Список ролей |
| POST | `/scenarios/{id}/roles` | Добавить роль |
| PATCH | `/scenarios/{id}/roles/{role_id}` | Обновить роль |
| DELETE | `/scenarios/{id}/roles/{role_id}` | Удалить роль |

### Шаги диалога
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/scenarios/{id}/steps` | Список шагов |
| POST | `/scenarios/{id}/steps` | Добавить шаг (реплику/реакцию) |
| PATCH | `/scenarios/{id}/steps/{step_id}` | Обновить шаг |
| DELETE | `/scenarios/{id}/steps/{step_id}` | Удалить шаг |
| POST | `/scenarios/{id}/steps/reorder` | Изменить порядок шагов |

### Аккаунты кампании
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/campaigns/{id}/accounts` | Список аккаунтов |
| POST | `/campaigns/{id}/accounts` | Привязать аккаунт(ы) |
| PATCH | `/campaigns/{id}/accounts/{acc_id}` | Назначить роль / пометить резервным |
| DELETE | `/campaigns/{id}/accounts/{acc_id}` | Отвязать |

### Целевые каналы
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/campaigns/{id}/targets` | Список целей |
| POST | `/campaigns/{id}/targets` | Bulk-добавление ссылок |
| DELETE | `/campaigns/{id}/targets/{target_id}` | Удалить цель |

### Чёрный список
| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/campaigns/{id}/blacklist` | Список ЧС |
| POST | `/campaigns/{id}/blacklist` | Добавить в ЧС |
| DELETE | `/campaigns/{id}/blacklist/{entry_id}` | Убрать из ЧС |

### Запуск и статистика
| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/campaigns/{id}/start` | Запустить кампанию |
| POST | `/campaigns/{id}/stop` | Остановить |
| POST | `/campaigns/{id}/dry-run` | Сухой прогон (тест) |
| GET | `/campaigns/{id}/stats` | Статистика |
| GET | `/campaigns/{id}/logs` | Логи выполнения |
| GET | `/campaigns/{id}/readiness` | Чеклист готовности к запуску |

---

## 6. Worker

### 6.1 Новые задачи (TaskName)

```python
# --- Модуль shilling ---
SHILLING_START_CAMPAIGN = "shilling.start_campaign"
SHILLING_PROCESS_TARGET = "shilling.process_target"
SHILLING_EXECUTE_STEP = "shilling.execute_step"
SHILLING_FAILOVER = "shilling.failover"
SHILLING_REVIVAL_TICK = "shilling.revival_tick"
SHILLING_DRY_RUN = "shilling.dry_run"
```

### 6.2 Orchestrator — жизненный цикл кампании

```
start_campaign
    │
    ├─ Валидация: аккаунты, сценарий, цели — всё OK?
    │
    ├─ Для каждого target (канал):
    │   │
    │   ├─ Проверить ЧС → пропустить если в ЧС
    │   ├─ Проверить open comments → пропустить если закрыты
    │   ├─ Найти последний пост → выбрать
    │   │
    │   ├─ Для каждого step в сценарии:
    │   │   │
    │   │   ├─ Выбрать аккаунт по роли (основной или резервный)
    │   │   ├─ Если unique_messages → LLM рерайт текста
    │   │   ├─ Если use_chat_context → подтянуть контекст поста
    │   │   │
    │   │   ├─ execute_step:
    │   │   │   ├─ Governor rate-limit check
    │   │   │   ├─ around_telethon_call → send_message / send_reaction
    │   │   │   ├─ Запись в execution_log
    │   │   │   └─ При ошибке → failover (замена на резерв)
    │   │   │
    │   │   └─ Пауза (reply_delay)
    │   │
    │   └─ Пауза между целями (target_delay)
    │
    └─ Завершение: статус completed / error
```

### 6.3 Failover — замена аккаунта при бане

При получении `PeerFlood`, `UserBannedInChannel`, `ChatWriteForbidden`:

1. Текущий аккаунт помечается как `failed` в логе
2. Канал добавляется в ЧС для этого аккаунта
3. Из резервного пула берётся следующий аккаунт
4. Сценарий продолжается с текущего шага новым аккаунтом
5. Если резерв исчерпан → логирование, переход к следующей цели

### 6.4 Revival — оживление чата

```
revival_tick (cron, каждые N минут)
    │
    ├─ Выбрать аккаунты для этого чата
    ├─ LLM генерирует тему + реплики (2–5 шт)
    ├─ Распределить реплики по аккаунтам
    ├─ Последовательная отправка с задержками
    └─ Запланировать следующий tick
```

---

## 7. LLM-интеграция

### 7.1 Промпт для рерайтинга (ReplicaRewriter)

Используется при `unique_messages=true`. На вход: базовый текст реплики + роль +
бренд + (опционально) контекст поста. На выход: уникализированный текст,
сохраняющий смысл и упоминание бренда.

```
Системный промпт:
Ты — рерайтер реплик для Telegram-чата. Перепиши текст так, чтобы он
звучал естественно, как будто написан реальным пользователем.

Правила:
- Сохрани упоминание бренда/продукта ТОЧНО как задано
- Не добавляй ссылки, @username, хэштеги
- Стиль: разговорный, неформальный, с опечатками/сленгом если уместно
- Длина: примерно та же, что у оригинала (±20%)
- Роль персонажа: {role_name} ({role_character})

Вход: «{original_text}»
Бренд: «{brand_name}»
Контекст поста (если есть): «{post_context}»
```

### 7.2 Промпт для генерации сценария (ScenarioGenerator)

Используется при нажатии «Сгенерировать через ИИ».

```
Системный промпт:
Ты — сценарист нативных диалогов для Telegram-чатов. Создай естественную
переписку между {persons_count} участниками.

Правила:
- Тема: {topic}
- Бренд для упоминания: {brand_name}
- Роли: {roles_list}
- Длина: {steps_count} реплик
- Бренд упоминается ТОЛЬКО в ответах, НЕ в первом вопросе
- Никаких ссылок, @username, хэштегов, явной рекламы
- Стиль: живой разговор, неформальный
- Каждый участник говорит своим стилем (из описания роли)

Формат ответа: JSON массив шагов:
[
  {"role": "Инициатор", "text": "...", "reply_to_step": null},
  {"role": "Ответчик", "text": "...", "reply_to_step": 1},
  ...
]
```

### 7.3 Промпт для оживления чата (RevivalGenerator)

```
Системный промпт:
Ты генерируешь тематический диалог для Telegram-группы.

Тема группы: {topic}
Участники: {persons_count} аккаунтов
Стиль: {tone} (дружеский/экспертный/неформальный)

Создай короткий диалог (3–6 реплик) на тему, которая:
- Интересна аудитории группы
- Побуждает к дискуссии
- Звучит как реальное обсуждение, а не сгенерированный текст

Формат: JSON массив [{"author_index": 0, "text": "..."}]
```

---

## 8. Frontend / UI

### 8.1 Маршруты

```tsx
// App.tsx — новые маршруты
<Route path="/modules/shilling" element={<ShillingScreen />} />
<Route path="/modules/shilling/campaigns/new" element={<NewShillingCampaignScreen />} />
<Route path="/modules/shilling/campaigns/:id" element={<ShillingCampaignDetailScreen />} />
```

Сайдбар (`DesktopSidebar.tsx`): новый пункт в секции MAIN:
```tsx
{ to: "/modules/shilling", label: "НейроШиллинг", icon: MessageSquareMore,
  alsoActiveOn: ["/modules/shilling"] }
```

### 8.2 Структура файлов фронтенда

```
frontend/src/modules/shilling/
├── ShillingScreen.tsx              # Список кампаний
├── NewShillingCampaignScreen.tsx    # Создание новой кампании
├── ShillingCampaignDetailScreen.tsx # Детали + все настройки
├── api.ts                          # API-клиент
├── types.ts                        # TypeScript типы
└── components/
    ├── ScenarioBuilder.tsx          # Конструктор сценария (роли + шаги)
    ├── ScenarioPreview.tsx          # Превью диалога в стиле мессенджера
    ├── RoleCard.tsx                 # Карточка роли
    ├── StepBubble.tsx              # Бабл сообщения (шаг сценария)
    ├── TargetsSection.tsx          # Секция целевых каналов
    ├── BlacklistSection.tsx         # Чёрный список
    ├── AccountAssignment.tsx       # Привязка аккаунтов к ролям
    ├── CampaignSettings.tsx        # Настройки кампании
    ├── LaunchPanel.tsx             # Панель запуска + чеклист + сухой прогон
    ├── StatsPanel.tsx              # Статистика
    ├── ExecutionLogList.tsx         # Лог выполнения
    ├── ModeSwitch.tsx              # Переключатель Кампания / Оживление чата
    └── RevivalSettings.tsx         # Настройки режима оживления
```

### 8.3 Экран кампании — структура блоков (сверху вниз)

#### Заголовок
- Название кампании (редактируемое)
- Бейдж статуса: Draft / Ready / Running / Paused / Completed
- Toggle вкл/выкл

#### Блок «Аккаунты»
- Карточка: «Выбрано: N, нужно минимум {persons_count}»
- Кнопка «Выбрать аккаунты» → BottomSheet выбора
- Список привязанных аккаунтов с назначенными ролями
- Возможность drag-and-drop назначения роли

#### Блок «Конфигурация сценария» (collapsible)
- **Переключатель режима**: [Кампания] / [Оживление чата] — tab-style
- **Для режима «Кампания»**:
  - Тема обсуждения (textarea) + кнопка «Сгенерировать через ИИ»
  - Медиа (загрузка фото/видео к репликам)
  - Бренд/ссылка — обязательное поле (input)
  - Сколько персон: counter (- N +)
  - Тумблеры: Уникальные сообщения / Контекст чата
  - Пауза между репликами: от ___ до ___ (с)
  - Длина сценария: input / «ИИ» (LLM сам определит)
  - Роли придумывает ИИ: toggle
  - **Секция РОЛИ**: карточки ролей с буквой + название + характер.
    Кнопка «+ Добавить роль». Крестик для удаления.
  - **Секция ШАГИ ДИАЛОГА**: визуальный конструктор реплик.
    Бабблы сообщений как в мессенджере (роль → текст → #номер → задержка).
    Кнопки «+ Реплика», «+ Реакция».
    Клик по баблу → редактирование.
  - Кнопка «Превью» — показывает диалог в стиле мессенджера
  - Кнопка «Использовать сценарий» — подтверждение

- **Для режима «Оживление чата»**:
  - Тематика чата (textarea)
  - Тон общения: select (дружеский / экспертный / неформальный / смешанный)
  - Кол-во участников: counter
  - Интенсивность: сообщений в час (slider)
  - Длина диалога: кол-во реплик за цикл

#### Блок «Настройка кампании» (collapsible)
- **Цели**: textarea (@username, t.me/... — Enter; можно списком)
  Счётчик целей. Кнопка «Из базы» (заглушка для будущего парсера).
- **Пауза между целями**: мин / макс (с)
- **Расширенные настройки** (collapsible):
  - Лимиты на аккаунт: сообщений/час, всего сообщений
  - Автоответчик: Выключен / НейроДиалоги / Ответ в чате
  - Резерв: toggle (если роль-аккаунт забанят)
  - Отвечать реальным людям: toggle (аккаунты остаются в чате)

#### Блок «Запуск кампании» (collapsible)
- **Чеклист**: Аккаунты выбраны N/M ○ Сценарий утверждён ○ Цели добавлены N
- **Сухой прогон**: кнопка «Проверить» — тест без отправки
- Панель: Аккаунты | Цели | Роли | Реплик | Диалог займёт
- Кнопки: Запустить / Пауза / Расписание (отложенный запуск)

#### Блок «История» (collapsible)
- Статистика: Всего попыток | Успешно | Ошибки | Процент успеха
- Кнопка «Открыть полную историю» → детальный лог

#### Блок «Чёрный список» (collapsible)
- Input + кнопки «Добавить», «Загрузить файл»
- Таблица: поиск, фильтр по причине, экспорт TXT/CSV, очистка
- Автоматическое добавление при банах/отказах

---

## 9. Этапы разработки

### Этап 1: Фундамент (Backend — модели и миграции)
**Цель**: создать всю структуру данных в БД.

- [ ] Создать `modules/shilling/` со всей структурой каталогов
- [ ] Добавить `SHILLING_SCHEMA = "shilling"` в `core/models/base.py`
- [ ] ORM-модели: `ShillingCampaign`, `ShillingScenario`, `ShillingScenarioRole`,
      `ShillingScenarioStep`, `ShillingCampaignAccount`, `ShillingTarget`,
      `ShillingExecutionLog`, `ShillingBlacklist`
- [ ] Реэкспорт моделей в `core/models/__init__.py`
- [ ] Alembic-миграция для схемы `shilling`
- [ ] Repository-классы для всех моделей
- [ ] Pydantic-схемы (Create/Read/Update) для каждой сущности

**Зависимости**: нет.
**Оценка**: 2-3 дня.

---

### Этап 2: API — CRUD-эндпоинты
**Цель**: все REST-эндпоинты для управления кампаниями.

- [ ] `modules/shilling/api/router.py` — FastAPI-роутер
- [ ] `modules/shilling/api/service.py` — бизнес-логика
- [ ] CRUD кампаний + переключение статуса
- [ ] CRUD сценариев + ролей + шагов
- [ ] Привязка/отвязка аккаунтов с ролями
- [ ] Bulk-добавление целей
- [ ] Чёрный список (CRUD + авто-добавление)
- [ ] Эндпоинт readiness (чеклист готовности)
- [ ] Эндпоинт stats (статистика)
- [ ] Подключить роутер в `api/main.py`

**Зависимости**: Этап 1.
**Оценка**: 2-3 дня.

---

### Этап 3: LLM — генерация и рерайтинг
**Цель**: промпты и адаптеры для ИИ-функций.

- [ ] `modules/shilling/llm/rewriter.py` — рерайтинг реплик
- [ ] `modules/shilling/llm/scenario_generator.py` — генерация сценария
- [ ] `modules/shilling/llm/revival_generator.py` — генерация для оживления
- [ ] API-эндпоинт `POST /campaigns/{id}/scenario/generate`
- [ ] Тесты с FakeProvider

**Зависимости**: Этап 2.
**Оценка**: 1-2 дня.

---

### Этап 4: Worker — оркестратор и исполнитель
**Цель**: вся backend-логика выполнения кампаний.

- [ ] Добавить `TaskName` для шиллинга в `core/queue/task_names.py`
- [ ] `modules/shilling/worker/registry.py` — регистрация задач
- [ ] `modules/shilling/worker/orchestrator.py`:
  - `start_campaign` — валидация + запуск цикла по целям
  - `process_target` — валидация канала + цикл по шагам
  - Обработка пауз между целями
- [ ] `modules/shilling/worker/executor.py`:
  - `execute_step` — отправка одной реплики/реакции
  - Интеграция с Governor (rate-limit)
  - Интеграция с `around_telethon_call`
  - Запись в execution_log
  - Failover-логика (замена аккаунта из резерва)
- [ ] `modules/shilling/worker/revival.py`:
  - `revival_tick` — цикл оживления чата
- [ ] Dry-run (сухой прогон без реальной отправки)
- [ ] Подключение задач в `worker/main.py`

**Зависимости**: Этап 2, Этап 3.
**Оценка**: 3-4 дня.

---

### Этап 5: Frontend — каркас и навигация
**Цель**: базовый UI — список кампаний, создание, навигация.

- [ ] `frontend/src/modules/shilling/types.ts` — TypeScript типы
- [ ] `frontend/src/modules/shilling/api.ts` — API-клиент
- [ ] `ShillingScreen.tsx` — список кампаний (карточки)
- [ ] `NewShillingCampaignScreen.tsx` — форма создания
- [ ] Добавить маршруты в `App.tsx`
- [ ] Добавить пункт «НейроШиллинг» в `DesktopSidebar.tsx` и `BottomNav.tsx`
- [ ] Компонент `ModeSwitch.tsx` — переключатель режимов

**Зависимости**: Этап 2.
**Оценка**: 1-2 дня.

---

### Этап 6: Frontend — конструктор сценариев
**Цель**: визуальный редактор сценариев — ключевой UI блок.

- [ ] `RoleCard.tsx` — карточка роли (цвет, имя, характер, удаление)
- [ ] `StepBubble.tsx` — бабл реплики в стиле мессенджера
- [ ] `ScenarioBuilder.tsx` — полный конструктор:
  - Управление ролями (добавить/удалить/редактировать)
  - Управление шагами (добавить реплику/реакцию, удалить, переупорядочить)
  - Назначение роли на шаг
  - Выбор reply_to (на какое сообщение отвечает)
  - Индивидуальные задержки
  - Редактирование текста по клику
- [ ] `ScenarioPreview.tsx` — превью в стиле чата Telegram
- [ ] Кнопка «Сгенерировать через ИИ» → вызов API
- [ ] Кнопка «Использовать сценарий» → применение черновика

**Зависимости**: Этап 5.
**Оценка**: 3-4 дня.

---

### Этап 7: Frontend — настройки кампании и запуск
**Цель**: все остальные блоки UI.

- [ ] `AccountAssignment.tsx` — привязка аккаунтов к ролям
- [ ] `CampaignSettings.tsx` — настройки (задержки, лимиты, тумблеры)
- [ ] `TargetsSection.tsx` — управление целями
- [ ] `BlacklistSection.tsx` — чёрный список
- [ ] `LaunchPanel.tsx`:
  - Чеклист готовности (аккаунты / сценарий / цели)
  - Сухой прогон (кнопка «Проверить»)
  - Кнопки запуска / паузы
  - Расчёт времени выполнения
- [ ] `StatsPanel.tsx` — статистика + краткая история
- [ ] `ExecutionLogList.tsx` — подробный лог
- [ ] `RevivalSettings.tsx` — настройки для режима оживления

**Зависимости**: Этап 6.
**Оценка**: 2-3 дня.

---

### Этап 8: Интеграция и тестирование
**Цель**: всё работает end-to-end.

- [ ] Тест: создание кампании → настройка сценария → добавление целей → запуск →
      проверка логов
- [ ] Тест failover: блокировка аккаунта → замена на резервный
- [ ] Тест dry-run: прогон без реальной отправки
- [ ] Тест revival: оживление собственного чата
- [ ] Тест уникализации: одинаковый сценарий → разные тексты для разных каналов
- [ ] UI-тесты: все блоки рендерятся, формы валидируются
- [ ] Проверка лимитов (billing): ограничение по плану

**Зависимости**: Этапы 1-7.
**Оценка**: 2-3 дня.

---

## Сводка по срокам

| Этап | Описание | Оценка |
|------|----------|--------|
| 1 | Фундамент (модели + миграции) | 2-3 дня |
| 2 | API (CRUD) | 2-3 дня |
| 3 | LLM (генерация + рерайтинг) | 1-2 дня |
| 4 | Worker (оркестратор + executor) | 3-4 дня |
| 5 | Frontend (каркас) | 1-2 дня |
| 6 | Frontend (конструктор сценариев) | 3-4 дня |
| 7 | Frontend (настройки + запуск) | 2-3 дня |
| 8 | Интеграция + тесты | 2-3 дня |
| **Итого** | | **16-24 дня** |

---

## Что НЕ входит (отложено)

- **Парсер каналов** — отдельная функция (будущий модуль), пока ручной ввод
- **Подготовка профилей** — уже существует в `modules/profiles/` и
  `modules/bulk/actions/apply_profile.py`
- **Шаблоны/пресеты сценариев** — можно добавить позже (флаг `is_template`
  уже заложен в модели)
- **Отложенный запуск по расписанию** — можно добавить через cron-задачу
