# Integration Audit — «висящий» функционал

Аудит от 2026-09-12. Метод: чтение реальных потоков выполнения + grep вызовов
(исключая `tests/` и `.venv`), `alembic check`. Код не менялся.

**Вывод коротко:** серверные слои и юнит-логика на месте и протестированы, но
несколько ключевых «стыков» между модулями не подключены к реальному рантайму —
самый критичный обрыв цепочки в жизненном цикле аккаунта: после логина аккаунт
попадает в `warming` и **там застревает навсегда**, потому что первичный прогрев
никто не запускает. Это каскадом убивает и весь commenting (нет аккаунтов в
`pool` → нечего аттачить в кампании).

## Сводная таблица

| # | Место | Ожидание | Факт | Severity |
|---|-------|----------|------|----------|
| 1 | `account.start_warming` (`worker/tasks/handlers.py`) | После `login_confirm`/`login_password` переход created→warming ставит задачу запуска прогрева | ✅ **CLOSED (2026-09-13):** устранено прямым enqueue из `_finish_login` (`login/flow.py`), задача-обёртка `account.start_warming` удалена как лишняя (убрана из `_STUB_TASKS` и из `TaskName`). ~~Была заглушкой в `_STUB_TASKS` и никем не enqueue'илась.~~ | **CLOSED** |
| 2 | `warming.initial_start` (`worker/tasks/warming.py:197`) | Вызывается из `account.start_warming`, планирует стартовую пачку `warming.tick` | ✅ **CLOSED (2026-09-13):** `warming.initial_start` зарегистрирована как arq-задача (`TaskName.WARMING_INITIAL_START`) и enqueue'ится из `_finish_login` сразу после перехода created→warming; она планирует стартовую пачку `warming.tick`. ~~Была определена, но не вызывалась и не была зарегистрирована.~~ | **CLOSED** |
| 3 | `health.check_proxies` (`worker/tasks/health.py:34`) | Реальный SOCKS5/HTTP-хендшейк (проверка, что прокси реально проксирует, с авторизацией) | Реализован `socket.create_connection((host, port))` — **простой TCP-connect**, не заглушка, но и не хендшейк: не проверяет тип прокси, авторизацию и фактическое проксирование | **major** |
| 4 | Регистрация NewMessage-слушателей (`modules/commenting/worker/listener.py`) | При старте воркера подключаются слушатели для всех enabled-кампаний; динамика при create/enable/disable | ✅ **CLOSED (2026-09-13):** `worker/main.py::startup` вызывает `ListenerRegistry.load_all(ctx)` после готового `client_pool`. Динамика без рестарта: API публикует `campaign_lifecycle` (`{campaign_id, action}`) при смене `enabled` (PATCH) / удалении / привязке первого аккаунта, а `CampaignLifecycleListener` (фоновая задача воркера) делает `attach`/`detach` по событию. `start_listeners` (всё-сразу) переработан в поштучные `attach`/`detach` в `registry.py`. ~~Не вызывался, динамики не было.~~ | **CLOSED** |
| 5 | Entry-point API (`api/main.py`) | Запускаемый сервер (uvicorn/gunicorn, host/port/workers из конфига) | ✅ **CLOSED (2026-09-13):** `api/asgi.py::create_app()` — прод-фабрика с lifespan (fail-fast `SELECT 1` к Postgres + `PING` к Redis, таймауты коннекта, graceful `dispose`/`close`), CORS (origin Mini App из `WEBAPP_ORIGIN`, всё в DEV), request-id middleware (uuid → structlog contextvars → заголовок `X-Request-ID`) и глобальный обработчик ошибок (500 `{error, request_id}`, стектрейс только в лог). `app` (ленивый, PEP 562) — цель `gunicorn -c deploy/gunicorn.conf.py api.asgi:app`. `api/main.py` остаётся «голым» для тестов. | **CLOSED** |
| 6 | Зависимости (`pyproject.toml`) | Все runtime-импорты объявлены с версиями | ✅ **CLOSED (2026-09-13):** `httpx` перенесён в runtime; `google-generativeai`, `redis`, `uvicorn[standard]`, `gunicorn` добавлены в runtime с версиями; dev-секция отдельно (pytest/fakeredis). Также `packages.find` расширен (`core*/api*/worker*/modules*`) — без этого `pip install .` не ставил worker/api/modules и импорт `worker.llm.*` в чистом venv падал. | **CLOSED** |
| 7 | `Governor` (`worker/health/governor.py`) | `check_and_reserve` вызывается из **всех** исходящих действий в Telegram (warming, posting, login) | Вызывается **только** в `commenting/worker/runner.py::post_comment` (`action_type='comment'`). В warming-действиях, `warming.tick` и логине governor **не используется** → лимиты `warming`/`login` из конфига мертвы | **major** |
| 8 | `around_telethon_call` (`worker/health/monitor.py`) | Оборачивает **все** реальные вызовы Telethon (warming, login, posting) | Используется **только** в `post_comment`. Warming-действия зовут `client(...)` напрямую (ловится лишь action-декоратором → `status=failed`, но `HealthEvent`/cooldown НЕ создаются). Логин (`send_code_request`/`sign_in`) не обёрнут (свой разбор FloodWait→reschedule, но без `HealthEvent`/cooldown на spam/ban/session_revoked) | **major** |
| 9 | Redis pub/sub | Все события для API публикуются (login state, health alerts, warming progress) | `login` — публикуется воркером (`login/flow.py`), потребляется `LoginEventHub` → **работает**. `account_status` — публикуется state machine, но **ни один API-потребитель не подписан** (`LoginEventHub` слушает только `login`); вдобавок `api/deps/queue.py::get_publisher()` возвращает **`None`**, поэтому переходы, инициированные из API (attach/detach, retire, acknowledge_ban), не публикуют вообще ничего. `warming progress` — **канала/публикации нет**. `health alerts` — pub/sub нет, только запись в БД (мониторинг опрашивает БД) | **major** |
| 10 | Миграции vs модели | Нет расхождений (`alembic check`) | `alembic check` против тестовой БД (head 0002): **«No new upgrade operations detected»** — дрейфа нет. Оговорка: dev-БД мигрируется только вручную (нет runtime-шага `alembic upgrade`; авто-накат только в тестовом conftest) | **minor** |

## Дополнительно найденное (сверх списка)

| # | Место | Ожидание | Факт | Severity |
|---|-------|----------|------|----------|
| 11 | Каскад #1+#2 | created→warming→pool работает end-to-end | ✅ **CLOSED (2026-09-13):** как следствие закрытия #1/#2 путь created→warming→pool теперь запускается естественно от `login_confirm`/`login_password` (регрессионный e2e-тест `test_login_confirm_to_pool_without_manual_initial_start` в `tests/test_warming.py` проходит без ручного вызова `initial_start`). ~~Аккаунт застревал в `warming`.~~ | **CLOSED** |
| 12 | `ClientPool` в воркере (`worker/main.py`) | Пул кладётся в `ctx` при старте | ✅ **CLOSED (2026-09-13):** `startup` кладёт `ClientPool` в `ctx['client_pool']` явно и СРАЗУ (до `load_all` и прочих зависимых инициализаций); ленивое `_pool(ctx)` в login/warming/commenting теперь переиспользует готовый пул. В `shutdown` — `close_all`. | **CLOSED** |
| 13 | Прогрев: выбор целей (`worker/warming/actions/base.py`) | Подписки/чтение по интересам персоны | Хардкод `DISCOVERY_CHANNELS = ("telegram","durov","tginfo")` — плейсхолдер, каталога по интересам персоны нет | **minor** |
| 14 | `account.retire` / `account.acknowledge_ban` как arq-задачи | Реализованы | Как **задачи-заглушки** (`_STUB_TASKS`). Функционально работают через API `/accounts/{id}/actions/*` (синхронно, через state machine), но задачи очереди — пустышки | **minor** |

## Рекомендованный порядок устранения (для планирования, не выполнено)

1. ✅ **#1/#2/#11 — CLOSED (2026-09-13).** Прогрев запускается прямым enqueue `warming.initial_start` из `login/flow.py::_finish_login` сразу после перехода created→warming; лишняя задача-обёртка `account.start_warming` удалена. Пайплайн created→warming→pool замкнут (см. строки #1/#2/#11).
2. ✅ **#4 + #12 — CLOSED (2026-09-13).** `ClientPool` кладётся в `ctx` при старте; слушатели подключаются через `ListenerRegistry.load_all`; динамика кампаний — через pub/sub-канал `campaign_lifecycle` и фоновую `CampaignLifecycleListener` (attach/detach без рестарта). См. строки #4/#12.
3. ✅ **#5 + #6 — CLOSED (2026-09-13).** ASGI entry-point `api.asgi:app` (create_app + lifespan/CORS/request-id/error-handler) + gunicorn-конфиг; зависимости приведены в runtime-секцию с версиями, `packages.find` починен. См. строки #5/#6.
4. **#7/#8** — прогнать warming/login-вызовы Telethon через `around_telethon_call` и governor.
5. **#9** — определить, какие каналы pub/sub реально нужны API, и включить публикацию (в т.ч. `get_publisher` в API).
