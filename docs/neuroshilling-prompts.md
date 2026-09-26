# НейроШиллинг — План реализации по промптам

Каждый промпт — самостоятельная задача для одной итерации разработки.
Промпты выполнять **строго по порядку**: следующий опирается на код предыдущего.

**Референс-документы** (агент читает перед каждым промптом):
- `docs/neuroshilling-spec.md` — полная спецификация модуля
- `docs/neuroshilling-ui-ux.md` — UI/UX дизайн

**Как работать с этим документом**:
1. Копируешь промпт целиком
2. Отдаёшь его агенту
3. Ждёшь готового результата (код + коммит)
4. Переходишь к следующему

---

## Этап 1 · Фундамент (Backend — модели, миграции, репозитории)

### Промпт 1.1 — Каркас пакета `modules/shilling/` и схема БД

```
Прочитай docs/neuroshilling-spec.md (разделы 2, 3) и создай каркас нового
модуля НейроШиллинг:

1. Создай директорию modules/shilling/ со структурой пакетов:
   - modules/shilling/__init__.py
   - modules/shilling/api/__init__.py
   - modules/shilling/models/__init__.py
   - modules/shilling/repositories/__init__.py
   - modules/shilling/schemas/__init__.py
   - modules/shilling/worker/__init__.py
   - modules/shilling/llm/__init__.py

2. В core/models/base.py добавь константу:
   SHILLING_SCHEMA = "shilling"

3. Создай пустую Alembic-миграцию с созданием схемы:
   CREATE SCHEMA IF NOT EXISTS shilling;

4. Убедись, что импорт `import modules.shilling` работает и Alembic видит
   новую миграцию.

НЕ создавай пока никаких моделей — только каркас.

Сделай коммит: "feat(shilling): scaffold module package and DB schema".
```

---

### Промпт 1.2 — ORM-модели кампании и сценария

```
Прочитай docs/neuroshilling-spec.md (раздел 3, таблицы 3.1–3.4) и создай
ORM-модели SQLAlchemy 2.x в modules/shilling/models/:

- campaign.py — ShillingCampaign (таблица 3.1)
- scenario.py — ShillingScenario (таблица 3.2)
- scenario_role.py — ShillingScenarioRole (таблица 3.3)
- scenario_step.py — ShillingScenarioStep (таблица 3.4)

Требования:
- Все таблицы в схеме shilling (используй SHILLING_SCHEMA константу)
- Наследуй от core.models.base.Base + TimestampMixin где нужно
- Используй паттерн из modules/commenting/models/campaign.py как референс
- Добавь CheckConstraint для всех enum-полей (mode, status, step_type,
  llm_provider)
- Добавь ForeignKey между таблицами (scenario_id → scenarios, role_id → roles)
  с правильным ondelete (CASCADE для дочерних, SET NULL для связок)
- Реэкспортируй модели в modules/shilling/models/__init__.py
- Добавь реэкспорт в core/models/__init__.py по аналогии с core.models.commenting

Затем создай Alembic-миграцию, которая создаёт все 4 таблицы.

Сделай коммит: "feat(shilling): add campaign and scenario ORM models".
```

---

### Промпт 1.3 — ORM-модели аккаунтов, целей, логов, чёрного списка

```
Прочитай docs/neuroshilling-spec.md (раздел 3, таблицы 3.5–3.8) и создай
оставшиеся ORM-модели в modules/shilling/models/:

- campaign_account.py — ShillingCampaignAccount (таблица 3.5)
- campaign_target.py — ShillingTarget (таблица 3.6)
- execution_log.py — ShillingExecutionLog (таблица 3.7)
- blacklist.py — ShillingBlacklist (таблица 3.8)

Требования:
- Схема shilling
- FK на core.models.account.Account (account_id) с ondelete=CASCADE
- FK на campaigns/targets/scenarios/roles/steps соответственно
- Уникальные индексы: (campaign_id, account_id) для campaign_account,
  (campaign_id, chat_id/username) для blacklist
- CheckConstraint для status enum и kind enum

Добавь миграцию, создающую эти 4 таблицы.

Реэкспорт в modules/shilling/models/__init__.py и в core/models/__init__.py.

Сделай коммит: "feat(shilling): add account, target, log, blacklist models".
```

---

### Промпт 1.4 — Repository-классы

```
Прочитай modules/commenting/repositories/campaign.py как эталон и создай
Repository-классы для всех моделей шиллинга в modules/shilling/repositories/:

- campaign.py — CampaignRepository
- scenario.py — ScenarioRepository, ScenarioRoleRepository, ScenarioStepRepository
- campaign_account.py — CampaignAccountRepository
- campaign_target.py — CampaignTargetRepository
- execution_log.py — ExecutionLogRepository
- blacklist.py — BlacklistRepository

Каждый должен иметь методы:
- get(id) → модель | None
- list_all() / list_by_campaign(campaign_id) → list
- create(schema) → модель
- update(id, schema) → модель | None
- delete(id) → bool

Дополнительно:
- CampaignAccountRepository: attach(campaign_id, account_id, role_id, is_reserve),
  detach(campaign_id, account_id), reassign_role(...)
- ScenarioStepRepository: reorder(scenario_id, step_ids_in_order),
  list_by_role(role_id)
- BlacklistRepository: is_blacklisted(campaign_id, chat_id_or_username) → bool

Все методы принимают Session первым аргументом (не self.session — сессия
передаётся снаружи, паттерн проекта).

Реэкспорт в modules/shilling/repositories/__init__.py.

Сделай коммит: "feat(shilling): add repository classes".
```

---

### Промпт 1.5 — Pydantic-схемы

```
Прочитай modules/commenting/schemas/campaign.py как эталон и создай
Pydantic-схемы в modules/shilling/schemas/:

- campaign.py — CampaignCreate, CampaignRead, CampaignUpdate
- scenario.py — ScenarioCreate, ScenarioRead, ScenarioUpdate,
  RoleCreate, RoleRead, RoleUpdate,
  StepCreate, StepRead, StepUpdate, StepReorderRequest
- campaign_account.py — AttachAccountRequest, CampaignAccountRead,
  CampaignAccountUpdate
- campaign_target.py — TargetCreate, TargetRead, TargetBulkCreate
- execution_log.py — ExecutionLogRead
- blacklist.py — BlacklistCreate, BlacklistRead
- stats.py — CampaignStats (total/sent/failed/success_rate),
  CampaignReadiness (accounts_ok/scenario_ok/targets_ok + причины)

Требования:
- Read-схемы имеют model_config = ConfigDict(from_attributes=True)
- Enum-поля типизируй через Literal[...] (не строкой)
- Все Update-схемы имеют все поля Optional
- Валидируй бизнес-правила: reply_delay_min <= reply_delay_max,
  target_delay_min <= target_delay_max, persons_count >= 2

Реэкспорт в modules/shilling/schemas/__init__.py.

Сделай коммит: "feat(shilling): add pydantic schemas".
```

---

## Этап 2 · API (CRUD-эндпоинты)

### Промпт 2.1 — Роутер + CRUD кампаний

```
Прочитай docs/neuroshilling-spec.md (раздел 4) и modules/commenting/api/router.py
как эталон. Создай:

1. modules/shilling/api/router.py с APIRouter(prefix="/modules/shilling",
   tags=["shilling"], dependencies=[Depends(require_user)])

2. Эндпоинты CRUD кампаний:
   - GET  /campaigns
   - POST /campaigns (+ enforce_limit проверка лимитов плана)
   - GET  /campaigns/{id}
   - PATCH /campaigns/{id}
   - DELETE /campaigns/{id}

3. modules/shilling/api/service.py с классами исключений:
   - ShillingNotFound, ShillingConflict, ShillingValidation

4. Подключи роутер в api/asgi.py (по аналогии с commenting).

Сделай коммит: "feat(shilling): add campaign CRUD API".
```

---

### Промпт 2.2 — API сценариев, ролей, шагов

```
Добавь в modules/shilling/api/router.py эндпоинты:

Сценарии:
- GET  /campaigns/{id}/scenario
- PUT  /campaigns/{id}/scenario (создать или заменить)

Роли:
- GET  /scenarios/{id}/roles
- POST /scenarios/{id}/roles
- PATCH /scenarios/{id}/roles/{role_id}
- DELETE /scenarios/{id}/roles/{role_id}

Шаги:
- GET  /scenarios/{id}/steps
- POST /scenarios/{id}/steps
- PATCH /scenarios/{id}/steps/{step_id}
- DELETE /scenarios/{id}/steps/{step_id}
- POST /scenarios/{id}/steps/reorder (body: list[step_id] в новом порядке)

Валидация в service.py:
- Нельзя удалить роль, если на неё ссылаются шаги (409 Conflict, с подсказкой
  «сначала удалите N шагов этой роли»)
- Нельзя удалить шаг, если на него ссылаются другие через reply_to_step_id
  (переназначить reply_to = None автоматически, залогировать)
- reorder — атомарная операция в транзакции

Сделай коммит: "feat(shilling): add scenario/roles/steps API".
```

---

### Промпт 2.3 — API аккаунтов кампании, целей, ЧС

```
Добавь в modules/shilling/api/router.py эндпоинты:

Аккаунты кампании:
- GET  /campaigns/{id}/accounts
- POST /campaigns/{id}/accounts (body: {account_id, role_id?, is_reserve?})
- PATCH /campaigns/{id}/accounts/{account_id} (сменить роль / резерв)
- DELETE /campaigns/{id}/accounts/{account_id}

Цели:
- GET  /campaigns/{id}/targets
- POST /campaigns/{id}/targets (body: {raw_inputs: list[str]})
   — bulk-добавление, дубли пропускаем молча
- DELETE /campaigns/{id}/targets/{target_id}

Чёрный список:
- GET  /campaigns/{id}/blacklist
- POST /campaigns/{id}/blacklist
- DELETE /campaigns/{id}/blacklist/{entry_id}

Валидация в service.py:
- Нельзя привязать один и тот же аккаунт дважды (409)
- Роль должна принадлежать сценарию этой же кампании (400)
- Аккаунт должен быть status=assigned (400)

Сделай коммит: "feat(shilling): add account/target/blacklist API".
```

---

### Промпт 2.4 — API статуса запуска, статистики, готовности

```
Добавь в modules/shilling/api/router.py:

- GET /campaigns/{id}/readiness → CampaignReadiness
   Возвращает: accounts_ok (>= persons_count), scenario_ok (роли покрыты,
   шаги валидны), targets_ok (>= 1 резолвнутый target). Плюс причины,
   почему что-то не готово.

- GET /campaigns/{id}/stats → CampaignStats
   Агрегат ExecutionLog по статусам: total, sent, failed, skipped,
   success_rate_percent.

- GET /campaigns/{id}/logs?status=&limit=50&offset=0
   Список ExecutionLog с фильтром.

- POST /campaigns/{id}/start — переводит status в 'running', публикует
   TaskName.SHILLING_START_CAMPAIGN в очередь. 409, если уже running.

- POST /campaigns/{id}/stop — переводит status в 'paused'. Задачи-в-полёте
   должны сами проверять кампанию перед выполнением и пропускать paused.

- POST /campaigns/{id}/dry-run — публикует TaskName.SHILLING_DRY_RUN,
   возвращает job_id, результат забирается через SSE (см. shared/sse.ts).

Сделай коммит: "feat(shilling): add readiness/stats/start/stop/dry-run API".
```

---

## Этап 3 · LLM (генерация и рерайтинг)

### Промпт 3.1 — Рерайтер реплик

```
Прочитай docs/neuroshilling-spec.md (раздел 6.1) и создай
modules/shilling/llm/rewriter.py:

Класс ReplicaRewriter принимает LLMProvider (из worker.llm.base).
Метод rewrite(original_text, role_name, role_character, brand_name,
post_context=None) → str.

Системный промпт — из спеки, раздел 6.1. Возвращает переписанный текст.

Требования:
- Провайдер инъектируется (тесты подставляют FakeProvider)
- Если бренд не сохранился в ответе — вставить его в конец через тире
  (fallback safety)
- Обрезать длину до max_length = len(original) * 1.5 (не даём LLM
  раздувать реплики)
- Тест с FakeProvider в tests/shilling/test_rewriter.py

Сделай коммит: "feat(shilling): add LLM replica rewriter".
```

---

### Промпт 3.2 — Генератор сценариев

```
Прочитай docs/neuroshilling-spec.md (раздел 6.2) и создай
modules/shilling/llm/scenario_generator.py:

Класс ScenarioGenerator принимает LLMProvider.
Метод generate(topic, brand_name, persons_count, steps_count=None,
roles=None) → GeneratedScenario (dataclass с roles: list, steps: list).

Если roles=None — генерируем и роли, и шаги.
Если roles заданы — используем их, генерируем только шаги.
Если steps_count=None — LLM сам решает (2*persons_count по умолчанию).

Системный промпт — из спеки, раздел 6.2. Ответ — строгий JSON, парсим
через json.loads с fallback на _JSON_BLOCK regex (см. modules/profiles/generator.py).

Валидация ответа:
- Каждый шаг имеет валидную роль из списка
- reply_to_step указывает на существующий шаг с меньшим индексом
- Бренд упомянут минимум в одном шаге (иначе retry с добавлением явного
  требования)

Добавь API-эндпоинт POST /campaigns/{id}/scenario/generate:
- Body: {topic, brand_name (или из кампании), persons_count, steps_count?}
- Возвращает GeneratedScenario, НЕ сохраняет в БД
   (фронт сам решит, применять или нет через PUT /campaigns/{id}/scenario)

Тест в tests/shilling/test_scenario_generator.py.

Сделай коммит: "feat(shilling): add LLM scenario generator".
```

---

## Этап 4 · Worker (оркестратор + executor + failover)

### Промпт 4.1 — TaskName + регистрация задач

```
Прочитай docs/neuroshilling-spec.md (раздел 5.1) и modules/commenting/worker/registry.py
как эталон.

1. Добавь в core/queue/task_names.py enum-константы:
   SHILLING_START_CAMPAIGN = "shilling.start_campaign"
   SHILLING_PROCESS_TARGET = "shilling.process_target"
   SHILLING_EXECUTE_STEP = "shilling.execute_step"
   SHILLING_FAILOVER = "shilling.failover"
   SHILLING_DRY_RUN = "shilling.dry_run"

2. Создай modules/shilling/worker/registry.py с функциями регистрации
   задач в arq. Публикация lifecycle-событий через Publisher (по аналогии
   с commenting).

3. Пустые заглушки функций start_campaign, process_target, execute_step,
   failover, dry_run в orchestrator.py / executor.py — просто логируют вызов
   и возвращают 0. Реальная логика в следующих промптах.

4. Подключи регистрацию в worker/main.py.

Проверь: воркер стартует, задачи видны в arq.

Сделай коммит: "feat(shilling): register worker tasks".
```

---

### Промпт 4.2 — Executor (отправка одного шага)

```
Прочитай docs/neuroshilling-spec.md (разделы 5.2, 5.3) и
modules/commenting/worker/runner.py как эталон.

Реализуй в modules/shilling/worker/executor.py функцию execute_step(ctx,
campaign_id, target_id, step_id, account_id, thread_msg_id=None):

Логика:
1. Загрузить кампанию, шаг, аккаунт из БД
2. Проверить кампанию enabled и status == 'running' → иначе выйти
3. Проверить active_hours (используй is_within_active_hours из commenting)
4. Governor.check_and_reserve(account_id, "shilling") → если нет слота,
   перепланировать через 5 минут
5. Если шаг unique_messages → вызвать ReplicaRewriter, иначе брать step.text
6. Через ClientPool получить клиента, вызвать around_telethon_call:
   - Для step_type='message': client.send_message(target.resolved_chat_id,
     text, reply_to=in_reply_to_message_id или thread_msg_id)
   - Для step_type='reaction': client.send_reaction(chat, message_id,
     step.reaction_emoji)
7. Записать ExecutionLog со status='sent' и posted_message_id
8. При исключениях PeerFlood/UserBannedInChannel/ChatWriteForbidden:
   - Записать лог со status='failed', error=<class>
   - Публикнуть TaskName.SHILLING_FAILOVER с текущим контекстом (см. 4.3)
9. При любом другом Exception — status='failed' и raise (arq retry)

Инъекции через ctx (для тестов): now, rng, session_factory, client_pool,
task_queue, governor, llm_provider.

Тест: tests/shilling/test_executor.py с моком клиента.

Сделай коммит: "feat(shilling): implement step executor with failover trigger".
```

---

### Промпт 4.3 — Failover (замена аккаунта из резерва)

```
Реализуй в modules/shilling/worker/orchestrator.py функцию failover(ctx,
campaign_id, target_id, step_id, failed_account_id, thread_msg_id=None):

Логика:
1. Загрузить связки campaign_account для кампании
2. Найти is_reserve=True аккаунты той же роли, что и failed_account
3. Отфильтровать те, что status='assigned' и не в execution_log этой цели
   со status='failed' (не пробуем повторно)
4. Если резерв найден — attach его к роли, detach failed_account,
   опубликовать SHILLING_EXECUTE_STEP с новым account_id
5. Если резерва нет — залогировать «резерв исчерпан», добавить target в
   blacklist автоматически (auto=True), продолжить со следующей цели

Обнови executor.py: catch-блок публикует SHILLING_FAILOVER вместо inline-логики.

Тест: tests/shilling/test_failover.py — три сценария:
- резерв доступен → замена происходит
- резерв исчерпан → target в blacklist
- failover для не-баньего исключения → не срабатывает

Сделай коммит: "feat(shilling): implement failover reserve rotation".
```

---

### Промпт 4.4 — Orchestrator (жизненный цикл кампании)

```
Реализуй в modules/shilling/worker/orchestrator.py:

1. start_campaign(ctx, campaign_id):
   - Валидация: аккаунтов >= persons_count, сценарий валиден, целей >= 1
   - При ошибке валидации → status='error', вернуть
   - Для каждого target из списка кампании → schedule SHILLING_PROCESS_TARGET
     с задержкой rng.uniform(target_delay_min, target_delay_max) относительно
     предыдущего
   - Логировать план запуска

2. process_target(ctx, campaign_id, target_id):
   - Проверить target не в blacklist (кампании ИЛИ глобальный)
   - Резолвнуть канал если ещё не резолвнут (client.get_entity)
   - Проверить discussion_group доступен, комментарии открыты
   - Взять последний пост канала → сохранить его message_id
   - Для каждого step в сценарии (по step_order):
     - Выбрать account по role (не резерв)
     - Schedule SHILLING_EXECUTE_STEP с задержкой delay_before_sec
       или rng.uniform(reply_delay_min, reply_delay_max)
     - Первый шаг → reply_to = post_message_id
     - Последующий шаг с reply_to_step_id → reply_to = posted_message_id
       из execution_log этого шага (нужен внутришаговый lookup)
   - Учитывать posts_per_target (лимит постов на канал)

3. После обработки всех targets → status='completed' если всё ок.

Тест: tests/shilling/test_orchestrator.py.

Сделай коммит: "feat(shilling): implement campaign orchestrator".
```

---

### Промпт 4.5 — Dry-run симулятор

```
Реализуй в modules/shilling/worker/dry_run.py функцию dry_run(ctx,
campaign_id, test_target_url):

Логика:
1. Валидация как в start_campaign
2. Для тестового канала (test_target_url) — резолв + проверка доступа
3. Симуляция шагов БЕЗ реальной отправки:
   - Для каждого шага — сгенерировать текст (если unique_messages → LLM)
   - Замерить симулированную задержку
   - Собрать пошаговый timeline: {step_id, account_id, role_name, text,
     scheduled_at_sec, risk_score}
4. Расчёт totals: длительность, количество сообщений/реакций,
   расход токенов LLM (примерно: n_steps * 200 токенов)
5. Публиковать через SSE-канал результаты по мере готовности
   (см. shared/sse.ts + core/queue/publisher.py)
6. Вернуть DryRunReport

Добавь SSE-эндпоинт GET /campaigns/{id}/dry-run/{job_id}/stream в API
для проксирования событий воркера в браузер.

Тест: tests/shilling/test_dry_run.py.

Сделай коммит: "feat(shilling): implement dry-run simulator with SSE".
```

---

## Этап 5 · Frontend (каркас и навигация)

### Промпт 5.1 — Типы, API-клиент, роутинг

```
Прочитай docs/neuroshilling-spec.md (раздел 7) и docs/neuroshilling-ui-ux.md
(разделы 3, 4).

1. Создай frontend/src/modules/shilling/types.ts — TypeScript-типы, зеркало
   modules/shilling/schemas (см. frontend/src/modules/commenting/types.ts как
   образец).

2. Создай frontend/src/modules/shilling/api.ts — API-клиент, используя
   apiClient из shared/api.ts (см. commenting/api.ts как образец).
   Экспортируй shillingApi объект со всеми методами: list, get, create,
   update, remove, scenario, updateScenario, generateScenario, roles,
   steps, accounts, attach, detach, targets, addTargets, removeTarget,
   blacklist, addBlacklist, removeBlacklist, readiness, stats, logs,
   start, stop, dryRun.

3. В frontend/src/App.tsx добавь маршруты:
   - /modules/shilling → ShillingListScreen
   - /modules/shilling/new → NewShillingWizard
   - /modules/shilling/:id → ShillingDetailScreen
     с вложенными табами (через nested Routes или query-param ?tab=)

4. В frontend/src/app/layout/DesktopSidebar.tsx добавь в MAIN пункт:
   { to: "/modules/shilling", label: "НейроШиллинг", icon: MessageSquareMore }

5. В frontend/src/app/layout/BottomNav.tsx добавь такой же пункт.

Сделай коммит: "feat(shilling-ui): types, api client, routing".
```

---

### Промпт 5.2 — Экран списка кампаний

```
Прочитай docs/neuroshilling-ui-ux.md (раздел 4.1) и создай
frontend/src/modules/shilling/ShillingListScreen.tsx:

Требования:
- useQuery для shillingApi.list()
- Фильтры-чипы: [Все] [Идут] [Пауза] [Черновики]
- Карточки кампаний с:
  - Название + статус-точка (пульсирующая для running — см. tokens.css)
  - Бренд, счётчики (аккаунты, цели N/M, успех %)
  - Прогресс-бар (использовать существующий утилити-класс или собрать из div)
  - Последняя активность (относительное время)
  - Кнопки [Пауза]/[Возобновить] и [Открыть →]
- Skeleton-loader при загрузке
- Empty state при 0 кампаний (иллюстрация + CTA «Создать первую»)
- Кнопка [+ Новая] в правом верхнем углу → навигация на /new

Используй существующие компоненты: card, Section, CapsuleButton,
statusDotClass из shared/status.ts.

Сделай коммит: "feat(shilling-ui): campaigns list screen".
```

---

### Промпт 5.3 — Wizard создания (шаги 1 и 3)

```
Прочитай docs/neuroshilling-ui-ux.md (раздел 4.2) и создай
frontend/src/modules/shilling/NewShillingWizard.tsx:

Каркас Wizard:
- Компонент WizardStepper вверху: ①—②—③ с активным шагом
- useState для draft-данных всех трёх шагов
- Кнопки [← Назад] [Далее →] / [Запустить]

Шаг 1: Основа (StepBasics.tsx)
- Название (TextInput)
- Бренд (TextInput с подсказкой «Как это будет выглядеть в диалоге»)
- Модель ИИ (SegmentedControl: DeepSeek / Gemini)
- Медиа (drop-zone для картинок — переиспользуй media_assets логику)

Шаг 2: Сценарий — заглушка (StepScenario.tsx)
- Placeholder «Конструктор сценария (реализуется в промпте 6.1)»

Шаг 3: Запуск (StepLaunch.tsx)
- Аккаунты — кнопка «Выбрать» открывает AccountPickerSheet (из commenting)
- Цели — TextArea с placeholder «@username, t.me/... — по одному в строке»
- Пауза между репликами (RangeField min/max)
- Пауза между целями (RangeField min/max)
- Лимиты (input сообщений/час, всего)
- Sanity-check панель: {✓ N аккаунтов, ✓ M целей, ✓ сценарий}
- Кнопки [Сухой прогон] [Запустить]

Валидация: далее нельзя, пока обязательные поля пустые.

На «Запустить» → shillingApi.create → shillingApi.start → навигация
на /modules/shilling/:id.

Сделай коммит: "feat(shilling-ui): creation wizard (basics + launch)".
```

---

### Промпт 5.4 — Экран деталей с табами

```
Прочитай docs/neuroshilling-ui-ux.md (раздел 4.3) и создай
frontend/src/modules/shilling/ShillingDetailScreen.tsx:

Layout:
- Шапка: название кампании + бейдж статуса + [⏸ Пауза]/[▶ Запустить]
- Ряд табов (SegmentedControl или свой Tabs):
  [Обзор] [Сценарий] [Аккаунты] [Цели] [История] [ЧС]
- Активный таб рендерит соответствующий компонент:
  - OverviewTab.tsx — live-метрики (счётчики + мини-график активности)
    + live-лог (последние 10 отправок с автоапдейтом каждые 5с)
    + быстрые действия
  - ScenarioTab.tsx — заглушка (полная реализация в 6.1)
  - AccountsTab.tsx — заглушка (реализация в 7.1)
  - TargetsTab.tsx — заглушка (реализация в 7.2)
  - HistoryTab.tsx — заглушка (реализация в 7.3)
  - BlacklistTab.tsx — заглушка (реализация в 7.3)
- Sticky-панель снизу (StickyLaunchPanel.tsx):
  - Чеклист {✓ аккаунты N/M, ✓ сценарий, ✗ цели 0}
  - [Сухой прогон] [🚀 Запустить] (disabled если чеклист неполный)

Данные:
- useQuery для campaign, readiness, stats
- refetchInterval: 5000 для readiness и stats

Используй haptic('light') на переключение табов.

Сделай коммит: "feat(shilling-ui): detail screen with tabs and sticky launch".
```

---

## Этап 6 · Frontend (конструктор сценариев — ключевая фича)

### Промпт 6.1 — Split-view редактор: каркас и левая колонка

```
Прочитай docs/neuroshilling-ui-ux.md (раздел 5.1, 5.2) и создай
frontend/src/modules/shilling/components/ScenarioBuilder.tsx.

Layout (десктоп ≥lg):
- Grid 2 колонки: [редактор 60%] [превью 40%]
- Мобайл (<lg): только редактор, превью в pinnable-полосе снизу

Левая колонка (Editor):
- Секция «РОЛИ»: горизонтальный список RoleCard.tsx карточек
  + кнопка [+ Добавить роль]
- Для каждой роли — колонка со списком её реплик StepBubble.tsx
  + кнопка [+ Реплика] и [+ Реакция] в конце колонки

Компонент RoleCard.tsx:
- Кружок с первой буквой + цвет из палитры (генерим hash от id)
- Название роли (inline-editable по клику)
- Характер (текст под названием, inline-editable по клику)
- Крестик удаления с confirm-диалогом

Компонент StepBubble.tsx:
- Бабл в стиле Telegram (rounded, surface-1)
- Текст реплики (inline-editable по клику)
- Ряд чипов:
  - [⏱ пауза Xс] → popover с двумя ползунками min/max
  - [↩ ответ на #N] → селект других шагов
  - [#порядковый_номер]
- Кнопки [✎] и [🗑] справа
- Для step_type='reaction' — вместо текста показывать эмодзи большим

Данные: props scenario: ScenarioRead, onChange: (draft) => void.
Все правки — оптимистичные локально, автосохранение по debounce 500ms.

Сделай коммит: "feat(shilling-ui): scenario builder editor column".
```

---

### Промпт 6.2 — Split-view редактор: превью

```
Создай frontend/src/modules/shilling/components/ScenarioPreview.tsx:

Layout — имитация экрана Telegram-чата:
- Шапка с иконкой канала (@пример) и названием
- Список сообщений в стиле мессенджера:
  - Бабблы с аватаркой (кружок с первой буквой роли, цвет тот же, что в
    RoleCard)
  - Имя роли над сообщением (мелким шрифтом)
  - Reply-цитата если reply_to_step_id указан (серый бордер + свёрнутый
    текст цитируемой реплики)
  - Реакции (эмодзи-чипы) отображаются как реакции на предыдущее сообщение
- Внизу — «💡 Диалог займёт ~Xс» (сумма всех delay + reply_delay средних)
- Кнопка «Сгенерировать через ИИ 🪄» — открывает модалку GenerateScenarioSheet

Props: scenario: ScenarioRead с уже приджойненными ролями/шагами.

Живая связь с редактором:
- При hover/фокусе на шаге в редакторе — соответствующий бабл в превью
  подсвечивается (outline + scale 1.02)
- Двусторонняя: hover на бабл → скролл к шагу в редакторе

Мобильная версия: свайп-вверх раскрывает fullscreen превью.

Сделай коммит: "feat(shilling-ui): scenario live preview (Telegram-style)".
```

---

### Промпт 6.3 — Модалка «Сгенерировать через ИИ»

```
Создай frontend/src/modules/shilling/components/GenerateScenarioSheet.tsx:

Bottom-sheet (моб.) / модалка (десктоп) с формой:
- Тема обсуждения (TextArea, обязательно)
- Бренд (TextInput, prefill из кампании)
- Кол-во персон (counter -/+, минимум 2, максимум 10)
- Кол-во реплик (input или toggle «ИИ решает»)
- Toggle «Роли придумывает ИИ» / «Использовать существующие»
- Кнопка [🪄 Сгенерировать] — вызывает shillingApi.generateScenario
- Loader с сообщениями «ИИ пишет диалог...»
- После получения ответа — превью сгенерированного сценария внутри модалки
- Кнопки [Применить] (перезапишет текущий scenario) / [Ещё раз]
  (retry с теми же параметрами) / [Отмена]

При применении — вызвать shillingApi.updateScenario и закрыть модалку.

Сделай коммит: "feat(shilling-ui): AI scenario generation modal".
```

---

## Этап 7 · Frontend (аккаунты, цели, история, ЧС)

### Промпт 7.1 — Таб «Аккаунты» с drag-and-drop резервом

```
Прочитай docs/neuroshilling-ui-ux.md (раздел 5.4) и создай
frontend/src/modules/shilling/components/AccountsTab.tsx:

Layout: две колонки [ОСНОВНЫЕ] и [РЕЗЕРВ]

Каждая карточка аккаунта:
- Health-точка (цвет из banRisk.ts)
- Аватарка/инициалы + телефон (mask)
- Селект роли (только для основных)
- Крестик отвязки

Drag-and-drop:
- Используй @dnd-kit/core (уже установлен? проверь frontend/package.json)
- Если не установлен — добавь. Runtime dependency.
- Перетаскивание между колонками → shillingApi.attach с обновлённым is_reserve
- Оптимистичные апдейты + откат при ошибке

Кнопка [+ Добавить из пула] → открывает AccountPickerSheet
(reuse из commenting) с фильтром на status='assigned' и не привязанных
к этой кампании.

Инсайт-подсказка (небольшая карточка сверху):
- Если у аккаунта banRisk.level == 'critical' → «Alice в критической зоне,
  лучше вынести в резерв»

Сделай коммит: "feat(shilling-ui): accounts tab with drag-and-drop reserve".
```

---

### Промпт 7.2 — Таб «Цели» с chip-редактором

```
Прочитай docs/neuroshilling-ui-ux.md (раздел 5.3) и создай
frontend/src/modules/shilling/components/TargetsTab.tsx:

Layout:
- Секция «ЦЕЛЕВЫЕ КАНАЛЫ» с чипами
- Каждый чип: иконка статуса (✓/⚠/⏳) + название канала + крестик удаления
- Клик по ⚠ → tooltip с last_error
- Ниже поле ввода [+ добавить: @username или t.me/...] с автосабмитом по Enter
- Кнопки [Вставить списком] (открывает модалку с textarea для bulk),
  [Импорт из файла] (upload .txt/.csv), [Из базы] (disabled с бейджем «скоро»)

Данные:
- useQuery на targets, refetchInterval: 3000 (пока идёт резолв)
- useMutation на addTargets, removeTarget с optimistic updates

Валидация ввода:
- Формат: @username или t.me/xxx или t.me/joinchat/xxx
- Дубли — не добавлять (показать toast «Уже в списке»)

Сделай коммит: "feat(shilling-ui): targets tab with chip editor".
```

---

### Промпт 7.3 — Табы «История» и «ЧС»

```
Создай frontend/src/modules/shilling/components/HistoryTab.tsx:

Layout:
- Ряд stat-tiles: [Всего попыток] [Успешно] [Ошибки] [Процент успеха]
- Мини-график активности за 7 дней (используй skill dataviz — sparkline)
- Инсайт-панель (см. docs/neuroshilling-ui-ux.md раздел 5.7):
   Показывать 2-3 наиболее релевантных инсайта на основе логов
   (простая эвристика на клиенте: топ-3 канала с failed, средний CTR
   каждого аккаунта)
- Полный лог: виртуализированный список (react-window или простая
  пагинация) с фильтрами:
  - Статус (SegmentedControl: All/Sent/Failed/Skipped)
  - Дата (диапазон)
  - Аккаунт (селект)
- Каждая строка: время + канал + аккаунт + роль + первые 60 символов текста
  + статус-точка
- Клик по строке → раскрытие с полным текстом и error

Создай frontend/src/modules/shilling/components/BlacklistTab.tsx:

Layout:
- Ряд действий: [+ Добавить] (input + кнопка), [Загрузить файл],
  [Экспорт TXT] [Экспорт CSV] [Очистить] (с confirm)
- Фильтры: поиск по чату, селект по причине
- Таблица: чат/username | причина | auto/manual бейдж | дата | [🗑]
- Empty state с иконкой щита

Сделай коммит: "feat(shilling-ui): history and blacklist tabs".
```

---

### Промпт 7.4 — Симулятор сухого прогона

```
Прочитай docs/neuroshilling-ui-ux.md (раздел 5.6) и создай
frontend/src/modules/shilling/components/DryRunSimulator.tsx:

Модалка/сайд-панель (открывается по кнопке из StickyLaunchPanel):

Форма запуска:
- Тестовый чат (TextInput с валидацией @/t.me)
- Кнопка [Запустить прогон]

Во время выполнения (SSE-стрим):
- Timeline с записями «00:04  Alice: «Ребята...» ✓» по мере поступления
- Индикатор прогресса

После завершения — сводка:
- 📊 Итого: N сообщений, M реакций, длительность
- 📊 Расход бюджета: ~$X.XX (LLM-токены)
- 📊 Риск-скор: 🟢/🟡/🔴 + пояснение
- Кнопки [Отправить в реальный чат] (запускает start), [Закрыть]

SSE через EventSource на /modules/shilling/campaigns/{id}/dry-run/{job_id}/stream
(см. shared/sse.ts как основа).

Сделай коммит: "feat(shilling-ui): dry-run simulator with SSE timeline".
```

---

## Этап 8 · Интеграция, полировка, тесты

### Промпт 8.1 — Wizard шаг 2 (интеграция ScenarioBuilder)

```
Обнови frontend/src/modules/shilling/NewShillingWizard.tsx:

Замени заглушку в StepScenario.tsx на полноценный ScenarioBuilder
из промпта 6.1.

Особенности в контексте wizard:
- Кнопка [Сгенерировать через ИИ] крупная, по центру, для новичков
- Draft-режим: сценарий не сохраняется в БД, хранится в state wizard
- При переходе на шаг 3 — валидация: минимум 1 роль, минимум 2 шага
- При финальном «Запустить» — сначала create campaign, потом
  updateScenario, потом start

Сделай коммит: "feat(shilling-ui): integrate scenario builder into wizard".
```

---

### Промпт 8.2 — Автосохранение и обработка ошибок

```
Пройди по всем экранам модуля shilling и убедись, что:

1. Автосохранение onBlur/debounce для всех редактируемых полей
   (паттерн AutoText из commenting/CampaignDetailScreen.tsx)
2. Показ «Сохранено» галочки на 1.5с после успешного сохранения
3. Toast с ошибкой если API упало (используй существующий toast-механизм
   или создай shared/toast.ts)
4. Optimistic updates для всех mutations (mutate → onError откат)
5. Skeleton-loader вместо спиннеров на всех useQuery
6. Empty states с иллюстрацией + CTA для всех пустых списков
   (создай shared/EmptyState.tsx или используй существующий
   components/EmptyState.tsx)

Сделай коммит: "feat(shilling-ui): autosave, error handling, empty states".
```

---

### Промпт 8.3 — E2E-тест базового флоу

```
Напиши интеграционный тест tests/shilling/test_e2e_campaign_flow.py:

Сценарий:
1. POST /modules/shilling/campaigns → создаётся draft-кампания
2. PUT /campaigns/{id}/scenario → добавляется сценарий с 2 ролями и 3 шагами
3. POST /campaigns/{id}/accounts x2 → привязываются 2 аккаунта на роли
4. POST /campaigns/{id}/targets → добавляется 1 цель
5. GET /campaigns/{id}/readiness → все три флага True
6. POST /campaigns/{id}/start → status='running', задача в очереди
7. Мокаем клиент Telegram, запускаем воркер вручную
8. Проверяем: execution_logs содержат 3 записи status='sent'
9. GET /campaigns/{id}/stats → total=3, sent=3, success_rate=100

Мок-инъекции:
- FakeLLMProvider возвращает заготовленный текст
- FakeClientPool возвращает мок с send_message returning stub

Сделай коммит: "test(shilling): add e2e campaign flow test".
```

---

### Промпт 8.4 — Тесты failover и dry-run

```
Напиши тесты:

tests/shilling/test_failover_flow.py:
- Создать кампанию с 2 основными аккаунтами и 1 резервным
- Первый аккаунт при send_message кидает UserBannedInChannel
- Проверить: SHILLING_FAILOVER опубликован, резервный назначен на роль,
  сценарий продолжен резервным

tests/shilling/test_dry_run_flow.py:
- Создать кампанию, вызвать /dry-run с test target
- Проверить: реальный send_message НЕ вызывался, только симуляция
- Проверить: DryRunReport содержит все шаги с корректными timings

Сделай коммит: "test(shilling): failover and dry-run tests".
```

---

### Промпт 8.5 — Проверка лимитов и биллинга

```
1. Изучи api/deps/limits.py и core/billing/ — как реализованы лимиты
   для commenting.

2. Добавь в core/billing/ (или где хранится PlanLimits) новые лимиты:
   - shilling_campaigns_active_max — сколько активных кампаний одновременно
   - shilling_targets_per_campaign_max — сколько целей на кампанию
   - shilling_scenario_steps_max — сколько шагов в сценарии

3. Примени enforce_limit в API:
   - POST /modules/shilling/campaigns → shilling_campaigns_active_max
   - POST /campaigns/{id}/targets → shilling_targets_per_campaign_max
   - POST /scenarios/{id}/steps → shilling_scenario_steps_max

4. В UI (StickyLaunchPanel и списке кампаний) — показывать LimitBanner
   когда лимит достигнут, с CTA «Обновить тариф».

5. Тест: при превышении лимита API возвращает 402/403 с понятным сообщением.

Сделай коммит: "feat(shilling): plan limits enforcement".
```

---

### Промпт 8.6 — Финальная полировка + документация

```
1. Пройди по всему модулю (Backend + Frontend), исправь:
   - Все type: ignore и any в TypeScript
   - Все print() и debug-логи (перевести на structlog)
   - Мёртвый код и закомментированные куски
   - Дублирование между commenting и shilling → выделить в shared

2. Обнови README проекта: добавь секцию «НейроШиллинг» с кратким описанием
   и ссылкой на docs/neuroshilling-spec.md.

3. Запусти линтеры и тесты:
   - pytest tests/shilling/
   - cd frontend && npm run typecheck
   - cd frontend && npm run lint (если есть)

4. Убедись, что модуль работает end-to-end локально:
   - docker-compose up
   - Открой /modules/shilling
   - Создай тестовую кампанию через wizard
   - Прогони через dry-run

Сделай коммит: "chore(shilling): final polish, docs, and lint fixes".
```

---

## Резюме: 28 промптов = полный модуль

| Этап | Промпты | Описание |
|------|---------|----------|
| 1. Фундамент | 1.1 – 1.5 | Пакет, схема БД, модели, репозитории, Pydantic |
| 2. API | 2.1 – 2.4 | CRUD + управление сценариями + статистика |
| 3. LLM | 3.1 – 3.2 | Рерайтер + генератор сценариев |
| 4. Worker | 4.1 – 4.5 | TaskNames + executor + failover + orchestrator + dry-run |
| 5. Frontend каркас | 5.1 – 5.4 | Типы, routing, список, wizard-каркас, детали с табами |
| 6. Конструктор сценариев | 6.1 – 6.3 | Split-view редактор + превью + AI-модалка |
| 7. Остальные табы | 7.1 – 7.4 | Аккаунты (D&D), Цели (чипы), История, ЧС, Симулятор |
| 8. Интеграция и полировка | 8.1 – 8.6 | Интеграция wizard, автосейв, тесты, лимиты, полировка |

**Оценка**: ~28 итераций, при темпе 1-2 промпта в день = **3-4 недели** на полный модуль.

## Как использовать

1. **По одному промпту за раз**. Не отдавай агенту два промпта сразу — он
   может потерять фокус или пропустить требования.
2. **Проверяй результат каждого промпта**: смотри коммит, запусти линтер,
   попробуй запустить UI/API.
3. **Если промпт не полностью выполнен** — не добавляй новые требования,
   а конкретно укажи, что не сделано, и попроси доделать.
4. **Ссылайся на предыдущие коммиты**, если следующий промпт что-то от них
   ожидает.
5. **Держи открытыми spec и ui-ux документы** — агент будет их читать в
   каждом промпте.
