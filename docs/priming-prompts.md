# Telegram-Прайминг — План реализации по промптам

Каждый промпт — самостоятельная задача для одной итерации разработки.
Промпты выполнять **строго по порядку**: следующий опирается на код
предыдущего.

**Референс-документы** (агент читает перед каждым промптом):
- `docs/priming-spec.md` — полная спецификация модуля
- `docs/priming-ui.md` — UI/UX модуля
- `docs/UI-DESIGN-BRIEF.md` — источник истины по стилю
- `docs/PROJECT-STAGES.md` — инварианты проекта

**Как работать**:
1. Копируешь промпт целиком.
2. Отдаёшь агенту.
3. Ждёшь коммита + прохождения `pytest` (и `npm run build` для фронта).
4. Переходишь к следующему.

**Общие правила для всех промптов** (агент подразумевает по умолчанию):
- Только Worker открывает `.session` / инстанцирует `TelegramClient`.
- API ↔ Worker — только через Redis.
- Все Telegram-действия — через rate-limit governor.
- Каждый прайминг-outcome логируется через `AccountStateMachine` /
  health-стрим.
- Не использовать мягкое удаление.
- Новый код покрывается тестами; интеграционные — с моком Telethon.

---

## Этап 0 · R&D по MTProto-триггерам

### Промпт 0.1 — Матрица кандидатов и тестовый скрипт

```
Прочитай docs/priming-spec.md §5.

Задача: подготовить **изолированный** R&D-скрипт в scripts/priming_rnd/,
который на двух тестовых аккаунтах (сессия из .env: PRIMING_RND_SESSION_A,
PRIMING_RND_SESSION_B) поочерёдно вызывает КАЖДЫЙ из пяти кандидатов
trigger_action и фиксирует:
  - какой MTProto-метод дёрнули (сигнатура),
  - какую RPC-ошибку получили (если получили),
  - остался ли артефакт в чате (сообщение / служебное событие),
  - реально ли приходит push у второй стороны (обязательный чекбокс
    оператора — YES/NO в CLI).

Требования к скрипту:
  - Аргументы CLI: --action, --target (username / user_id).
  - Использовать существующий `worker/client_pool` для запуска сессии,
    НЕ создавать новый TelegramClient напрямую.
  - Идёт через тот же rate-limit governor, что и продакшн.
  - На каждый прогон писать JSON-отчёт в scripts/priming_rnd/reports/
    (timestamp в имени).

Никакого кода в modules/priming/ не пишем.

По результату — сгенерировать `docs/priming-triggers.md` с таблицей:
`trigger_action | mtproto | push_seen | chat_artifact | notes` и
рекомендацией «взять в MVP» для 2–3 самых надёжных.

Коммит: "chore(priming): R&D script and trigger matrix".
```

---

## Этап 1 · Каркас модуля и БД

### Промпт 1.1 — Пакет modules/priming/ и схема БД

```
Прочитай docs/priming-spec.md §3.

1. Создай пакет modules/priming/ со структурой (все __init__.py пустые):
   - api/, models/, repositories/, schemas/,
     worker/, parser/, profile_setup/.

2. В core/models/base.py добавь константу:
      PRIMING_SCHEMA = "priming"

3. Создай Alembic-миграцию, создающую схему priming:
      CREATE SCHEMA IF NOT EXISTS priming;

4. Проверь, что `import modules.priming` работает и alembic upgrade head
   проходит.

Никаких моделей пока не заводим.

Коммит: "feat(priming): scaffold module package and DB schema".
```

### Промпт 1.2 — Enum'ы и общие Pydantic-схемы

```
Прочитай docs/priming-spec.md §4, §5.

Задача — единый источник enum'ов и базовых схем:
  - modules/priming/schemas/enums.py:
      PrimingCampaignStatus, PrimingMode, TriggerAction, HumanizerMode,
      WarmupProfile, PrimingAccountState, TargetStatus, TargetLastSeen,
      ExecutionOutcome, ParserSourceKind, BlacklistReason,
      AnchorChannelState.
  - Использовать `enum.StrEnum` (Python 3.11+).
  - modules/priming/schemas/common.py: базовые Pydantic BaseModel'и
    (Pagination, TimeRange, ErrorEnvelope).

Юнит-тесты в tests/priming/test_enums.py — проверяют значения и
несовместимые переходы (например, TargetStatus.PRIMED → PENDING запрещён).

Коммит: "feat(priming): enums and common schemas".
```

### Промпт 1.3 — ORM-модели: кампании, аккаунты, цели

```
Прочитай docs/priming-spec.md §4.1–4.3.

Создай ORM-модели SQLAlchemy 2.x в modules/priming/models/:
  - campaign.py           → PrimingCampaign        (§4.1)
  - campaign_account.py   → PrimingCampaignAccount (§4.2)
  - campaign_target.py    → PrimingCampaignTarget  (§4.3)

Требования:
  - Все таблицы в схеме priming (использовать PRIMING_SCHEMA).
  - Наследование от core.models.base.Base + TimestampMixin.
  - Референс паттернов — modules/shilling/models/.
  - FK на core.models.account.Account(account_id) с ondelete=CASCADE.
  - UNIQUE(campaign_id, account_id) в PrimingCampaignAccount.
  - CheckConstraint по всем enum-полям через enum'ы из 1.2.

Alembic-миграция создаёт три таблицы.

Реэкспорт в modules/priming/models/__init__.py и в core/models/__init__.py.

Коммит: "feat(priming): campaign / accounts / targets ORM".
```

### Промпт 1.4 — ORM-модели: sources, presets, anchor, log, blacklist

```
Прочитай docs/priming-spec.md §4.4–4.9.

Создай ORM-модели в modules/priming/models/:
  - target_source.py    → PrimingTargetSource     (§4.4)
  - profile_preset.py   → PrimingProfilePreset    (§4.5)
  - anchor_channel.py   → PrimingAnchorChannel    (§4.6)
  - execution_log.py    → PrimingExecutionLog     (§4.7)
  - flood_incident.py   → PrimingFloodIncident    (§4.8)
  - blacklist.py        → PrimingBlacklist        (§4.9)

Требования:
  - execution_log — append-only, без Update-триггеров.
  - blacklist поддерживает owner_user_id NULL (глобальный).
  - anchor_channel уникален по (account_id) — один активный канал
    на аккаунт.
  - Все FK, CheckConstraint, индексы — по спеке.

Alembic-миграция добавляет 6 таблиц.

Реэкспорт в __init__.py и core.models.

Коммит: "feat(priming): sources / presets / anchor / logs models".
```

### Промпт 1.5 — Repository-классы

```
Возьми modules/shilling/repositories/campaign.py как эталон.

Создай Repository-классы для каждой модели прайминга в
modules/priming/repositories/. Обязательные методы:
  - list_by_campaign, get_by_id, create, update, delete_hard.
  - Специфичные:
     * CampaignAccountRepository.acquire_next(campaign_id) — атомарный
       поиск свободного аккаунта с advisory-lock.
     * CampaignTargetRepository.claim_next(campaign_id, account_id) —
       атомарный переход pending → assigned под FOR UPDATE SKIP LOCKED.
     * ExecutionLogRepository.append(...) — append-only.
     * BlacklistRepository.match(owner_id, tg_user_id | username | phone).

Юнит-тесты на testcontainers-postgres или существующий postgres_test
из docker-compose.

Коммит: "feat(priming): repositories for all models".
```

### Промпт 1.6 — Pydantic-схемы Create/Read/Update

```
Прочитай docs/priming-spec.md §4, §6.

Создай Pydantic v2 схемы в modules/priming/schemas/:
  - campaign.py: PrimingCampaignCreate, ...Update, ...Read (с nested
    account/target счётчиками).
  - target.py, profile_preset.py, anchor_channel.py, parser.py, stats.py.

Валидация:
  - delay_between_targets_sec_min < _max, оба > 0.
  - daily_limit_per_account ∈ [1, 500].
  - stop_on_privacy_rate ∈ [0, 1].
  - При status='running' поля кампании кроме name/notes read-only —
    ловится в service layer (см. промпт 2.3), схема лишь помечает
    readonly для UI.

Юнит-тесты на валидацию.

Коммит: "feat(priming): create/read/update Pydantic schemas".
```

---

## Этап 2 · Ядро исполнения (MVP)

### Промпт 2.1 — TriggerRunner (обёртка над MTProto)

```
Прочитай docs/priming-spec.md §5 и docs/priming-triggers.md
(если создан на промпте 0.1).

Создай modules/priming/worker/trigger.py:

  class TriggerResult:
      outcome: ExecutionOutcome
      flood_wait_sec: int | None = None
      error_code: str | None = None
      latency_ms: int

  class TriggerRunner:
      def __init__(self, client: TelegramClient, governor: RateLimitGovernor): ...
      async def run(self, action: TriggerAction, target: TargetRef) -> TriggerResult: ...

Требования:
  - Каждый action = отдельный приватный метод (_run_secret_chat, ...).
  - Все Telethon-исключения маппятся в TriggerResult, не raise.
  - Идемпотентность: перед действием читать текущее состояние (если
    action уже применён — сразу вернуть outcome=ALREADY_APPLIED).
  - Всё измеряется latency_ms и репортится в execution_log.

Юнит-тесты с моком Telethon: FloodWaitError, UserPrivacyRestrictedError,
UsernameNotOccupiedError, deleted user, happy path.

Коммит: "feat(priming): trigger runner with MTProto action wrappers".
```

### Промпт 2.2 — Executor (одна единица прайминга)

```
Прочитай docs/priming-spec.md §7.1 (execute_prime).

Создай modules/priming/worker/executor.py:

  async def execute_prime(campaign_id, target_id, account_id) -> None:
    1. Через AccountStateMachine reserve(account_id, purpose="priming").
    2. Открыть TelegramClient через worker.client_pool.
    3. Через TriggerRunner (2.1) выполнить кампанийный trigger_action.
    4. ExecutionLogRepository.append(...) с outcome и latency.
    5. CampaignAccountRepository.increment_counters(outcome).
    6. CampaignTargetRepository.mark(target_id, outcome, ...).
    7. При FLOOD_WAIT — flood_incidents, обновить next_available_at,
       при переборе — quarantine.
    8. Освободить аккаунт.

Ставит через arq job `priming.execute_prime`.

Тесты: happy path, FLOOD_WAIT, privacy, quarantine после max_flood.
Все с моком TriggerRunner.

Коммит: "feat(priming): executor task with FLOOD/privacy handling".
```

### Промпт 2.3 — Orchestrator (tick-раскладчик)

```
Прочитай docs/priming-spec.md §7.1 (orchestrator_tick) и §7.2.

Создай modules/priming/worker/orchestrator.py:

  async def orchestrator_tick(campaign_id: int) -> None:
    - Проверить status кампании.
    - Для каждого campaign_account в state=idle с primes_today <
      daily_limit_per_account и next_available_at<=now:
        target = repos.targets.claim_next(campaign_id, account_id)
        if not target: break
        schedule executor.execute_prime(...)
        schedule next tick с рандом-delay из delay_between_targets_sec.
    - Проверить автостоп по stop_on_privacy_rate.
    - Если ни один аккаунт не может работать (все в cooldown или лимите)
      — reshedule tick через 60 сек.

Регистрация в worker/tasks/priming.py и подключение в arq settings.

Тесты: тик выдаёт правильное число execute_prime; при quarantine
аккаунта — пропускает; при stop_on_privacy_rate — переводит кампанию
в paused.

Коммит: "feat(priming): orchestrator tick with rate + autostop".
```

### Промпт 2.4 — Service слой + API-эндпоинты кампаний

```
Прочитай docs/priming-spec.md §6 (кампании и аккаунты).

Создай modules/priming/api/service.py и router.py.

Service:
  - create_campaign, update_campaign (только status=draft/paused),
    list_campaigns, get_campaign, start_campaign, pause, resume, stop,
    delete_campaign (только draft/finished/failed).
  - start_campaign валидирует: минимум 1 аккаунт, 1 цель, trigger_action
    поддерживается в билде, включён по фиче-флагу.
  - На start_campaign публикует orchestrator_tick в arq.

Router prefix /modules/priming, теги ["priming"].

Подключить в api/routing.py.

E2E-тесты через httpx + api.main.app: create → attach account →
attach target → start → check status; validation errors.

Коммит: "feat(priming): campaign service and REST endpoints".
```

### Промпт 2.5 — API аккаунтов и targets (ручной ввод / CSV)

```
Прочитай docs/priming-spec.md §6 (аккаунты и цели).

Расширь router и service:
  - POST /campaigns/{id}/accounts (bulk из пула, фильтр по warmup).
  - DELETE /campaigns/{id}/accounts/{account_id}.
  - POST /campaigns/{id}/targets/import — принимает JSON list ИЛИ
    multipart/form-data CSV (username, phone, user_id — любая из
    колонок опциональна, но хотя бы одна не пустая).
  - GET /campaigns/{id}/targets с filter по status.
  - POST /campaigns/{id}/targets/blacklist — массово.

Ограничения:
  - Один аккаунт — одна кампания-прайминг одновременно
    (проверка в service).
  - Импорт CSV делает дедуп по (tg_user_id | username | phone) и
    сверяется с глобальным blacklist.

Тесты: happy path, дубликаты, CSV с пустыми колонками, аккаунт уже
в другой кампании.

Коммит: "feat(priming): accounts/targets endpoints + CSV import".
```

### Промпт 2.6 — Dry-run режим

```
Расширь TriggerRunner (2.1) параметром dry_run: bool на кампании
(PrimingCampaign.dry_run BOOL DEFAULT false — миграция).

В dry_run:
  - Executor всё делает как обычно, но TriggerRunner.run возвращает
    случайный outcome по распределению из docs/priming-triggers.md
    (78% primed / 12% privacy / 8% flood / 2% deleted — параметры
    в конфиге).
  - Никакие Telethon-вызовы не идут.
  - execution_log помечается флагом `dry_run=true`.

UI-переключатель добавим позже (промпт 6.3).

Тесты: убедиться, что при dry_run=true нет ни одного вызова Telethon.

Коммит: "feat(priming): dry-run mode for safe UI/E2E testing".
```

### Промпт 2.7 — Минимальный экран «Кампании» на фронте

```
Прочитай docs/priming-ui.md §3, §4 и docs/UI-DESIGN-BRIEF.md.
Плагин frontend-design применяем ПОВЕРХ брифа (при конфликте —
побеждает бриф).

Создай frontend/src/modules/priming/:
  - screens/PrimingCampaignsList.tsx — список карточек кампаний
    (mock-данные пока не нужны; тянем из GET /modules/priming/campaigns).
  - components/CampaignCard.tsx.
  - components/StatusDot.tsx (8px, --status-*).
  - components/ProgressLine.tsx (4px, no gradient).
  - hooks/useCampaigns.ts (react-query).

Правила:
  - Использовать design tokens из frontend/src/styles/ (если нет —
    завести файл tokens.css с переменными из UI-DESIGN-BRIEF §2).
  - Заголовок «Прайминг» — 32/700/-0.02em.
  - Никаких shadow, никаких gradient.
  - FAB `+` — круг 56 px, --accent, floating.

Регистрация экрана в роутинге + пункт меню «Прайминг» в сайдбаре.

Скриншоты обязательно (Chromium через существующий /run скилл), приложить
в PR-описание.

Коммит: "feat(priming): campaigns list screen".
```

### Промпт 2.8 — Мастер новой кампании (§5.1–5.7 UI)

```
Прочитай docs/priming-ui.md §5 полностью.

Создай экран frontend/src/modules/priming/screens/PrimingCampaignNew.tsx:
  - Один вертикальный скролл, секции-карточки (§5.1–5.7 UI-доки).
  - Preview-lock-screen компонент PushPreview (§5.1) — с
    real-time-подстановкой имени первого выбранного аккаунта.
  - Sticky footer с summary «N акк · M целей» и CTA
    «Проверить и запустить» (--accent, disabled если валидатор
    падает).
  - Алерты по конфигурации — карточка с левой полосой --status-warning
    4 px (не заливка).
  - Все контролы для темпа/лимитов — крупные числа tabular-nums 22/700,
    label под ними --text-tertiary 12 px.

Пока без drawer-парсера (это промпт 3.3) — вкладка «Аудитория» показывает
только два таба: `CSV` и `Ручной`.

Скриншоты в PR.

Коммит: "feat(priming): campaign wizard screen (no parser yet)".
```

---

## Этап 3 · Парсер аудитории (отдельный модуль-сервис `parsing`)

> Парсер вынесен из прайминга в самостоятельный модуль
> ``modules/parsing/`` рядом с commenting/shilling/priming.
> Прайминг импортирует готовые списки через
> ``POST /modules/priming/campaigns/{id}/targets/import-list``.

### Промпт 3.1 — Парсер chat_messages

```
Прочитай docs/priming-spec.md §8.

Создай modules/priming/parser/chat_messages.py:
  parse(chat_ref, days_window, min_messages, collector_account_id)
    → PrimingTargetSource + N × PrimingCampaignTarget(status=pending).

Требования:
  - Использовать worker.client_pool для чтения через отдельный
    account-парсер (не тот, что будет праймить).
  - Пагинация через iter_messages(min_id/max_id) с ограничением по
    days_window.
  - Агрегация: `sender_id → count`, отбор count >= min_messages.
  - Не хранить сами тексты сообщений.
  - Идёт через governor.

Юнит-тесты с моком Telethon (стрим сообщений).

Job: priming.parser_run_chat_messages(source_id).

Коммит: "feat(priming): chat_messages parser".
```

### Промпт 3.2 — Парсер chat_members + фильтры

```
Прочитай docs/priming-spec.md §8.1, §8.2.

Добавь:
  - modules/priming/parser/chat_members.py: pagination через
    channels.GetParticipants, фильтр last_seen_bucket по user.status.
  - modules/priming/parser/filters.py: filter_username, filter_premium,
    filter_bots, filter_deleted, filter_admins, filter_blacklist.

Фильтры принимают stream целей и возвращают stream оставшихся.
Все счётчики (отброшено по причине X) записываются в
PrimingTargetSource.after_filters_count + JSON-разбивка.

Тесты с mock-User объектами.

Коммит: "feat(priming): chat_members parser and reusable filters".
```

### Промпт 3.3 — API парсера и drawer «Аудитория»

```
Прочитай docs/priming-spec.md §6, docs/priming-ui.md §5.3.

Backend:
  - POST /modules/priming/campaigns/{id}/targets/parse
    body: {source: enum, params: {...}}
    → 202 + job_id.
  - GET /modules/priming/campaigns/{id}/parse-jobs/{job_id}
    (redis-hash со статусом: queued|running|done|failed + отчёт).

Frontend:
  - PrimingAudienceDrawer.tsx (bottom-sheet 90 % высоты).
  - Табы: `Парсер · CSV · Ручной`.
  - Форма парсера: chat_ref, days_window (slider 1..60), min_messages.
  - Кнопка «Пропарсить» — polling job раз в 2 сек, показывает
    live-счётчик raw.
  - Итоговая карточка-отчёт (§5.3 UI): raw / after_filters / разбивка
    + CTA «Использовать N».

Скриншоты в PR.

Коммит: "feat(priming): parser API and audience drawer UI".
```

---

## Этап 4 · Оформление профилей (POC)

### Промпт 4.1 — Preset backend: identity + bio

```
Прочитай docs/priming-spec.md §9.

Backend:
  - modules/priming/profile_setup/bio.py: apply_identity(account_id,
    preset) — устанавливает first/last/username/bio через account.
    UpdateProfile + account.CheckUsername + account.UpdateUsername.
  - Идемпотентность: если поля уже совпадают — no-op.
  - Ретраи на username-коллизии: 3 попытки с суффиксами из preset'а.

API:
  - CRUD /modules/priming/profile-presets.
  - POST /modules/priming/accounts/{account_id}/apply-preset {preset_id,
    steps: ["identity", "avatar", "bio", "stories", "anchor"]}
    → job_id.

Job: priming.profile_apply(account_id, preset_id, steps).

Тесты: username-коллизия с суффиксом, идемпотентный повторный запуск.

Коммит: "feat(priming): profile preset backend (identity/bio)".
```

### Промпт 4.2 — Avatar + stories publisher

```
Backend:
  - modules/priming/profile_setup/avatar.py: apply_avatar — заливка
    из локальной директории `preset.avatar_source` или галереи сервиса.
    Дедуп по phash: если у другого аккаунта уже стоит фото с тем же
    phash — отказ + PrimingProfileApplyError("avatar_duplicate").
  - modules/priming/profile_setup/stories.py: publish_stories — по
    preset.stories_pool. Использует stories.SendStory + ссылку-стикер
    (если Premium).

Тесты (mocked): установка нового фото, отказ по дубликату,
публикация 3 stories.

Коммит: "feat(priming): avatar and stories publishers".
```

### Промпт 4.3 — Anchor-канал

```
Backend:
  - modules/priming/profile_setup/anchor_channel.py:
      ensure_anchor_channel(account_id, template)
        - если у аккаунта уже есть PrimingAnchorChannel state=ok — no-op;
        - создаёт канал, ставит аватар, публикует пост, закрепляет,
          привязывает к профилю через channels.EditPersonalChannel
          (fallback: если недоступно — записывает reason и переводит
          preset в mode "bio_only").
      reset_anchor_channel(account_id) — удаляет канал (только если
        state=reset_required).

Ошибки Premium-required и channel_creation_limit — понятные текстовые
outcome'ы, чтобы UI показал предупреждение.

Тесты с моком.

Коммит: "feat(priming): anchor channel setup with premium fallback".
```

### Промпт 4.4 — UI пресетов и bulk-apply

```
Прочитай docs/priming-ui.md §8.

Frontend:
  - screens/PrimingProfilePresets.tsx — каталог пресетов (карточки-preview).
  - screens/PrimingProfilePresetEdit.tsx — три секции (Личность / Bio / Оффер).
    Секция «Оффер» — три чекбокс-карточки (Anchor / Stories / Bio-link),
    раскрываются в форму.
  - components/AccountProfilePreview.tsx — live preview §9.4 UI-доки
    (обновляется при правке).
  - screens/PrimingProfileApply.tsx — bulk-панель: выбор аккаунтов,
    выбор шагов, кнопка «Применить», progress по каждому шагу.

Скриншоты в PR.

Коммит: "feat(priming): profile preset UI (catalog / edit / apply)".
```

---

## Этап 5 · Humanizer + мульти-action

### Промпт 5.1 — Humanizer heartbeat

```
Прочитай docs/priming-spec.md §10.

Создай modules/priming/worker/humanizer.py:
  - Job priming.humanizer_beat(account_id).
  - Действия по HumanizerMode:
      off       — не запускается.
      balanced  — прочитать 1–3 поста в случайном канале из общего пула
                  (worker/warming/channels.py уже держит пул).
      aggressive — то же + случайная реакция + просмотр stories.
  - Никаких сообщений незнакомцам.
  - Строго не пересекается по времени с priming.execute_prime того же
    аккаунта (advisory-lock).

Оркестратор (2.3): между запуском execute_prime и следующим tick'ом
для того же аккаунта — публиковать humanizer_beat.

Тесты с моком Telethon.

Коммит: "feat(priming): humanizer heartbeat and orchestrator integration".
```

### Промпт 5.2 — Мульти-action и ротация триггеров

```
Прочитай docs/priming-spec.md §5, §7.

Расширь PrimingCampaign:
  - trigger_action → trigger_actions (JSONB list из TriggerAction).
  - trigger_rotation_strategy: enum(random, round_robin, weighted).

Executor выбирает action в момент старта прайминга (не при постановке
задачи) — чтобы можно было менять список без перепланирования очереди.

Alembic-миграция (with backfill: перекладываем старое поле в массив).

Тесты: rotation стратегии равномерны на 1000 попыток.

UI: чекбоксы вместо радио (§5.1 UI), preview показывает пуш выбранного
дефолтного action.

Коммит: "feat(priming): multi-action rotation".
```

---

## Этап 6 · Прогрев, автостоп, health-интеграция, live-UI

### Промпт 6.1 — Warmup profiles и auto-ramp

```
Прочитай docs/priming-spec.md §11.1 и docs/priming-ui.md §9.3.

Backend:
  - core/config/priming_warmup.py: словарь профилей
      cold: day1_limit=5, day7_limit=20, delay_min=200, delay_max=600
      warm: day1_limit=15, day7_limit=30, delay_min=60,  delay_max=200
      hot:  day1_limit=35, day7_limit=40, delay_min=20,  delay_max=60
  - Orchestrator при выборе аккаунта вычисляет эффективный
    daily_limit_per_account = interp(warmup_day, profile).
  - Хранить warmup_started_at на PrimingCampaignAccount (миграция).

UI:
  - На карточке аккаунта в §6.3 UI — маленький график-ступенька
    «лимит по дням».

Тесты: интерполяция дневных лимитов; переключение профиля меняет
следующий tick, не текущий.

Коммит: "feat(priming): warmup profiles with linear ramp".
```

### Промпт 6.2 — Автостопы и health-интеграция

```
Прочитай docs/priming-spec.md §11.2.

Backend:
  - Orchestrator раз в тик считает privacy_rate/flood_rate на скользящем
    окне 200 execution_log записей.
  - При превышении threshold — пауза кампании + запись в
    core.audit + событие в HealthMonitor
    (`priming.autopause_privacy`, `priming.autopause_flood`).
  - Quarantine аккаунта — тоже событие в HealthMonitor.

Frontend:
  - На экране «Ход» — карточка-баннер если кампания на autopause
    (левая полоса --status-critical, кнопка «Понял / Продолжить»).

Тесты: паузу вызывает именно превышение окна, а не отдельная запись.

Коммит: "feat(priming): autostop and health events integration".
```

### Промпт 6.3 — Экран «Ход» и dry-run переключатель

```
Прочитай docs/priming-ui.md §6.

Frontend:
  - screens/PrimingCampaignRun.tsx — вкладка «Ход»:
      * Hero-KPI карточка (§6.1 UI) со спарклайном 24 ч (recharts или
        собственный SVG; линия 1.5 px, --status-active, лёгкая
        градиент-заливка 8 %).
      * Ряд мини-KPI (успех / privacy / flood / карантин) — горизонтальный
        скролл.
      * Список строк-аккаунтов (§6.3 UI) с точкой-статусом, свайп
        влево → карантин.
  - Тумблер `dry-run` в шапке кампании (только если status ∈ {draft,
    paused, stopped}).
  - WS/SSE подключение на /modules/priming/campaigns/{id}/live для
    real-time обновлений счётчиков и логов.

Скриншоты обязательно.

Коммит: "feat(priming): live run screen + dry-run toggle".
```

### Промпт 6.4 — Экран «Логи» и экспорт CSV

```
Прочитай docs/priming-ui.md §7.

Backend:
  - GET /modules/priming/campaigns/{id}/logs?outcome=&q=&cursor=
    keyset pagination по (started_at desc, id desc).
  - GET /modules/priming/campaigns/{id}/logs/export.csv — streaming.

Frontend:
  - screens/PrimingCampaignLogs.tsx:
      * Пилюли-фильтры по outcome.
      * Список строк-карточек с левой полосой цвета outcome.
      * Тап → bottom-sheet с raw payload.
      * Иконка ⤓ в шапке — экспорт (streaming download).

Тесты: paginated fetch, empty state, filter combining.

Коммит: "feat(priming): logs screen with filters and CSV export".
```

---

## Этап 7 · Улучшения и полировка

### Промпт 7.1 — Cross-module blacklist

```
Прочитай docs/priming-ui.md §9.7.

Backend:
  - Расширить существующие blacklist-таблицы (commenting/shilling)
    общим SQL-view core.blacklist_all с полем module.
  - PrimingBlacklistRepository.match дополнительно проверяет
    core.blacklist_all и core.shilling_blacklist по (tg_user_id) за
    окно N дней (config).
  - Miграция + тест cross-check.

Тесты: цель, помеченная в шиллинге за 7 дней, не приходит из парсера.

Коммит: "feat(priming): cross-module blacklist".
```

### Промпт 7.2 — «Тихие часы» цели

```
Прочитай docs/priming-ui.md §9.6.

Backend:
  - Опция кампании quiet_hours_target BOOL DEFAULT false (миграция).
  - Executor перед вызовом TriggerRunner: если ФИО чата-источника даёт
    гео и локальное время цели ∈ (00:00–07:00) — outcome=SKIPPED_QUIET.
  - Если гео нет — не блокируем.

UI: чекбокс в §5.5.

Тесты: TZ-aware проверка.

Коммит: "feat(priming): target quiet-hours skip".
```

### Промпт 7.3 — A/B пресетов

```
Прочитай docs/priming-ui.md §9.5.

Backend:
  - PrimingCampaign.profile_preset_ab: JSONB {a: id, b: id, split: 0.5}.
  - При apply-preset к аккаунтам — половина получает A, половина B.
  - Пометка в PrimingCampaignAccount.ab_bucket ('a'|'b').
  - Метрика: доля primed по bucket'ам в stats endpoint.

UI:
  - В шаге «Профиль-пресет» — тумблер «A/B тест» открывает второй селектор.
  - В «Ход» — два столбца KPI по bucket'ам.

Тесты: равномерность распределения на 1000 аккаунтах.

Коммит: "feat(priming): A/B profile preset split".
```

### Промпт 7.4 — Прогноз «Что произойдёт за час»

```
Прочитай docs/priming-ui.md §9.2.

Backend:
  - GET /modules/priming/campaigns/{id}/forecast → JSON
    {expected_primes_per_hour, expected_flood_per_hour, best_start_after}.
  - Считает по warmup-профилю, времени суток каждого аккаунта (гео),
    среднему privacy_rate последних 500 попыток этого пользователя.

Frontend:
  - На финальном шаге мастера (перед CTA) карточка-симуляция.

Тесты: расчёт с фиксированными входами.

Коммит: "feat(priming): pre-launch forecast card".
```

### Промпт 7.5 — Health-биометрия аккаунта (sparkline в строке)

```
Прочитай docs/priming-ui.md §9.8.

Backend:
  - GET /modules/priming/accounts/{account_id}/health-sparkline
    → 7 точек (successes, floods, privacy per day).

Frontend:
  - В компоненте PrimingAccountRow добавить SVG-sparkline 40×16 px.
  - Использовать --status-active для successes, --status-warning для
    flood, --status-critical для privacy как несколько тонких линий
    поверх (толщина 1 px).

Тесты: рендер компонента при пустых данных.

Коммит: "feat(priming): per-account 7-day health sparkline".
```

### Промпт 7.6 — Long-press FAB и «повторный запуск»

```
Прочитай docs/priming-ui.md §9.11.

Frontend:
  - На FAB в PrimingCampaignsList: long-press (700 мс) открывает
    bottom-sheet «Повторить последнюю кампанию»:
      * showcase карточка последней завершившейся кампании,
      * CTA «Запустить копию сейчас» → POST /campaigns/{id}/duplicate
        + auto-start (если валидатор проходит).

Backend:
  - POST /modules/priming/campaigns/{id}/duplicate → возвращает id
    новой draft-кампании со всеми настройками, аккаунтами и списком
    целей (только pending).

Тесты: дубликат не уносит executed_log и primed_at целей.

Коммит: "feat(priming): campaign duplicate + long-press quick-run".
```

### Промпт 7.7 — Пейволл и обновление сайдбара

```
Прочитай core/billing/ и модуль-пейволл существующего commenting.

Backend:
  - Добавить feature key `priming` в core.billing.FeatureFlag.
  - Middleware блокирует POST /modules/priming/* если фича не активна
    (кроме GET).

Frontend:
  - Если фича не куплена — вместо экранов модуля показываем
    ту же пейволл-капсулу, что у commenting/shilling, только с копирайтом
    «Прайминг — конверсия через системные Push».
  - Никакого оранжево-неонового CTA — просто --accent капсула.

Тесты: 402 на POST без фичи.

Коммит: "feat(priming): feature-flag paywall and sidebar entry".
```

### Промпт 7.8 — Финальная документация и soak-тест

```
1. Обновить docs/PROJECT-STAGES.md — добавить раздел «Priming».
2. README-раздел «Модуль прайминга» с ссылками на spec/ui/prompts.
3. scripts/priming_soak/ — sсript, гоняющий 7 дней prime+humanizer в
   dry_run на 5 аккаунтах; агрегирует статистику и падает при
   выходе за допуски.
4. Прогнать soak-тест 7 дней (или ускоренный, с CLOCK_SKEW=1440) в
   CI-nightly, приложить отчёт в PR.

Коммит: "docs(priming): finalize spec cross-links + add soak harness".
```

---

## Порядок и параллелизм

- Промпты одного этапа — строго по порядку.
- Между этапами допустимо параллелить фронт и бэк, но экран запуска
  (2.8) требует API из 2.4–2.5.
- Промпты Этапа 7 — независимы друг от друга и могут идти параллельно.

## Definition of Done для каждого промпта

- Код + миграции + тесты в одной PR.
- `pytest` зелёный локально и в CI.
- `alembic upgrade head` и `alembic downgrade -1` — успешны.
- Для фронт-промптов — `npm run build` без ошибок + приложенные
  скриншоты нужных экранов (light + dark темы, если применимо).
- Коммит-мессадж — точно как в промпте (для сохранения истории).
