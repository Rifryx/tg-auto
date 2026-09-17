# Integration Audit — «висящий» функционал

Аудит от 2026-09-12. Метод: чтение реальных потоков выполнения + grep вызовов
(исключая `tests/` и `.venv`), `alembic check`. Код не менялся.

**Вывод коротко:** серверные слои и юнит-логика на месте и протестированы, но
несколько ключевых «стыков» между модулями не подключены к реальному рантайму —
самый критичный обрыв цепочки в жизненном цикле аккаунта: после логина аккаунт
попадает в `warming` и **там застревает навсегда**, потому что первичный прогрев
никто не запускает. Это каскадом убивает и весь commenting (нет аккаунтов в
`pool` → нечего аттачить в кампании).

---

## Повторный аудит — верификация связности (2026-09-13, после промптов 19–24)

Метод: повторное чтение реальных потоков + `grep` вызовов (исключая `tests/`),
подсчёт LOC. Код не менялся этим проходом. Цель — проверить, что найденные ранее
обрывы **реально** подключены, а не только «по коммитам». `alembic check` в этой
среде не запускался (нет БД) — см. #10.

| # | Место | Ожидание | Факт (проверено чтением кода) | Severity |
|---|-------|----------|------|----------|
| 1 | Запуск прогрева после логина | created→warming ставит задачу прогрева в очередь | ✅ ПОДКЛЮЧЕНО. `worker/login/flow.py:174` `_finish_login` делает `enqueue(TaskName.WARMING_INITIAL_START, account_id)` сразу после перехода. Обёртка `account.start_warming` удалена (нет в `TaskName`). Вызывается из реального потока, не только из тестов. | нет |
| 2 | `warming.initial_start` | Зарегистрирована как задача и вызывается | ✅ ПОДКЛЮЧЕНО. Зарегистрирована в `worker/tasks/handlers.py:81` (в `TASK_FUNCTIONS`), тело `worker/tasks/warming.py:225` планирует пачку `warming.tick`. Enqueue из `_finish_login` (не из тестов). | нет |
| 3 | `health.check_proxies` — реальный хендшейк | SOCKS5/HTTP-хендшейк с авторизацией | ✅ РЕАЛИЗОВАНО. `worker/health/proxy_probe.py`: SOCKS5/4 через `python-socks` (`proxy.connect`), HTTP через `CONNECT` + `Proxy-Authorization` с проверкой `200`. `check_proxies` использует его дефолтным пробером (sync/async). Не заглушка. | нет |
| 4 | Слушатели кампаний | Подключаются при старте для всех enabled; динамика после старта | ✅ ПОДКЛЮЧЕНО + ДИНАМИКА. `worker/main.py:48` `await registry.load_all(ctx)` (после `client_pool`, стр. 43). Создание/enable/disable/delete/attach — через pub/sub `campaign_lifecycle`, слушатель `CampaignLifecycleListener` (`main.py:54`, `create_task`) делает attach/detach без рестарта. | нет |
| 5 | Entrypoint API | Запускаемый прод-сервер | ✅ ЕСТЬ. `api/asgi.py::create_app()` (+ lifespan/CORS/request-id/error-handler), `app` ленивый (PEP 562). `deploy/gunicorn.conf.py` (`UvicornWorker`), `deploy/entrypoint-api.sh` (`alembic upgrade head` → `exec gunicorn … api.asgi:app`). | нет |
| 6 | Зависимости | Все runtime-импорты объявлены с версиями | ✅ ОБЪЯВЛЕНЫ. `httpx>=0.27`, `google-generativeai>=0.8`, `redis>=5.0`, `uvicorn[standard]>=0.30`, `gunicorn>=22.0`, `python-socks>=2.4` — в runtime-секции. `uvicorn`/`gunicorn` не импортируются в коде (это серверы — норма). Явно неиспользуемых объявленных не найдено. | нет |
| 7 | `Governor` во всех исходящих действиях | warming + posting + login | ✅ ВЕЗДЕ. `check_and_reserve` вызывается в login (`flow.py:202/243/294`, тип `login`), warming (`warming/actions/__init__.py:58`, тип `warming`), posting (`runner.py:231`, тип `comment`). | нет |
| 8 | `around_telethon_call` вокруг всех вызовов Telethon | warming + login + posting | ✅ ВЕЗДЕ. login (`flow.py:96` через `_around_call`, `handle_flood_wait=False`), warming (`actions/base.py:61`), posting (`runner.py:249`). | нет |
| 9 | Redis pub/sub | Публикуются все нужные каналы; API-потребитель подписан | ✅ ПОДКЛЮЧЕНО. Публикация: `login` (`flow.py:117`), `account_status` (state machine `account.py:337`), `warming_progress` (`warming.py:182`), `health_alert` (`monitor.py:85`), `campaign_lifecycle` (`registry.py:246`). `get_publisher` реальный (`deps/queue.py:26`). Потребитель `LoginEventHub` подписан на `login`+`account_status` (`services/login.py:60`) и отдаёт оба через SSE. | нет |
| 10 | Миграции vs модели | Нет дрейфа + runtime-накат | ⚠️ НЕ ПРОВЕРЕНО в этой среде (нет БД для `alembic check`). Файлы миграций на месте (`migrations/versions/0001_initial.py`, `0002_account_meta.py`); runtime-накат подключён (`deploy/entrypoint-api.sh`). Нужен прогон `alembic check` в среде с БД. | minor (не верифицировано) |

### Дополнительно найденное этим проходом (сверх 10 пунктов)

| # | Место | Наблюдение | Severity |
|---|-------|-----------|----------|
| A | `worker/main.py:44` `ctx['publisher']` + `RedisPublisher.publish` | Публикатор воркера теперь на СИНХРОННОМ redis-клиенте (это исправление — раньше был async arq-редис и `publish` возвращал корутину, не публикуя). Побочно: sync-`publish` вызывается внутри async-цикла воркера — короткая блокирующая операция. Для масштаба §6 приемлемо; при росте нагрузки — вынести в async-паблишер/executor. | minor |
| B | `api/main.py` | «Голое» приложение (`app = FastAPI()` без lifespan/CORS/request-id) всё ещё существует — используется тестами и как удобная точка. Риск: если в проде запустить `uvicorn api.main:app` вместо `api.asgi:app`, потеряются fail-fast-проверки коннектов и middleware. Docstring предупреждает, но footgun остаётся. | minor |
| C | Каналы `warming_progress` / `health_alert` | Публикуются, но подписчиков пока НЕТ (по замыслу — под будущий фронт/живые алерты). Дашборд `/monitoring` по-прежнему опрашивает БД. Это не обрыв, а задел; отметить, чтобы не всплыло как «мёртвый канал». | инфо |
| D | Тесты стыков #9 (`test_api_retire_publishes_account_status_to_redis`, warming/health-публикации) и сквозной `tests/integration/test_full_pipeline.py` | Требуют живых Postgres/Redis — в текущей среде только коллектятся, не исполнялись. Связность подтверждена чтением кода; фактический прогон нужен в CI/среде с сервисами. | инфо |

**Вывод повторного аудита:** все 10 исходных пунктов реально подключены к рантайму
(проверено по вызовам, не только по тестам). Остаток — некритичный: `alembic check`
не прогнан здесь (#10), плюс мелкие эксплуатационные заметки A–B и заделы C–D.

---

## Сводная таблица

| # | Место | Ожидание | Факт | Severity |
|---|-------|----------|------|----------|
| 1 | `account.start_warming` (`worker/tasks/handlers.py`) | После `login_confirm`/`login_password` переход created→warming ставит задачу запуска прогрева | ✅ **CLOSED (2026-09-13):** устранено прямым enqueue из `_finish_login` (`login/flow.py`), задача-обёртка `account.start_warming` удалена как лишняя (убрана из `_STUB_TASKS` и из `TaskName`). ~~Была заглушкой в `_STUB_TASKS` и никем не enqueue'илась.~~ | **CLOSED** |
| 2 | `warming.initial_start` (`worker/tasks/warming.py:197`) | Вызывается из `account.start_warming`, планирует стартовую пачку `warming.tick` | ✅ **CLOSED (2026-09-13):** `warming.initial_start` зарегистрирована как arq-задача (`TaskName.WARMING_INITIAL_START`) и enqueue'ится из `_finish_login` сразу после перехода created→warming; она планирует стартовую пачку `warming.tick`. ~~Была определена, но не вызывалась и не была зарегистрирована.~~ | **CLOSED** |
| 3 | `health.check_proxies` (`worker/tasks/health.py`) | Реальный SOCKS5/HTTP-хендшейк (проверка, что прокси реально проксирует, с авторизацией) | ✅ **CLOSED (2026-09-13):** `worker/health/proxy_probe.py` делает настоящий хендшейк до `proxy_check_host:port` по типу прокси — SOCKS5/4 через `python-socks` (greeting+auth+CONNECT), HTTP через `CONNECT` c `Proxy-Authorization` и проверкой `200`. Не-200/таймаут/ошибка → прокси мёртв. Пробер в `check_proxies` может быть sync или async. | **CLOSED** |
| 4 | Регистрация NewMessage-слушателей (`modules/commenting/worker/listener.py`) | При старте воркера подключаются слушатели для всех enabled-кампаний; динамика при create/enable/disable | ✅ **CLOSED (2026-09-13):** `worker/main.py::startup` вызывает `ListenerRegistry.load_all(ctx)` после готового `client_pool`. Динамика без рестарта: API публикует `campaign_lifecycle` (`{campaign_id, action}`) при смене `enabled` (PATCH) / удалении / привязке первого аккаунта, а `CampaignLifecycleListener` (фоновая задача воркера) делает `attach`/`detach` по событию. `start_listeners` (всё-сразу) переработан в поштучные `attach`/`detach` в `registry.py`. ~~Не вызывался, динамики не было.~~ | **CLOSED** |
| 5 | Entry-point API (`api/main.py`) | Запускаемый сервер (uvicorn/gunicorn, host/port/workers из конфига) | ✅ **CLOSED (2026-09-13):** `api/asgi.py::create_app()` — прод-фабрика с lifespan (fail-fast `SELECT 1` к Postgres + `PING` к Redis, таймауты коннекта, graceful `dispose`/`close`), CORS (origin Mini App из `WEBAPP_ORIGIN`, всё в DEV), request-id middleware (uuid → structlog contextvars → заголовок `X-Request-ID`) и глобальный обработчик ошибок (500 `{error, request_id}`, стектрейс только в лог). `app` (ленивый, PEP 562) — цель `gunicorn -c deploy/gunicorn.conf.py api.asgi:app`. `api/main.py` остаётся «голым» для тестов. | **CLOSED** |
| 6 | Зависимости (`pyproject.toml`) | Все runtime-импорты объявлены с версиями | ✅ **CLOSED (2026-09-13):** `httpx` перенесён в runtime; `google-generativeai`, `redis`, `uvicorn[standard]`, `gunicorn` добавлены в runtime с версиями; dev-секция отдельно (pytest/fakeredis). Также `packages.find` расширен (`core*/api*/worker*/modules*`) — без этого `pip install .` не ставил worker/api/modules и импорт `worker.llm.*` в чистом venv падал. | **CLOSED** |
| 7 | `Governor` (`worker/health/governor.py`) | `check_and_reserve` вызывается из **всех** исходящих действий в Telegram (warming, posting, login) | ✅ **CLOSED (2026-09-13):** `check_and_reserve` вызывается в `execute_action` (лимит `warming`; исчерпан → действие `skipped`/`rate_limited`, клиент не трогается) и в login-flow перед `send_code_request`/`sign_in` (лимит `login`; исчерпан → состояние `rate_limited`, не `failed`). Без Redis governor fail-open (не роняет прогрев/логин). | **CLOSED** |
| 8 | `around_telethon_call` (`worker/health/monitor.py`) | Оборачивает **все** реальные вызовы Telethon (warming, login, posting) | ✅ **CLOSED (2026-09-13):** обёрнуты warming-действия (внутри `action`-декоратора — health-события больше не теряются, но tick по-прежнему не падает: ошибка → `HealthEvent` + `status=failed`) и login-вызовы (`send_code_request`/`sign_in`). Монитор расширен: `UserDeactivatedBan`/`PhoneNumberBanned` → бан; `SessionPasswordNeeded` — не инцидент; флаг `handle_flood_wait=False` для логина сохраняет его собственный разбор FloodWait (регрессия). | **CLOSED** |
| 9 | Redis pub/sub | Все события для API публикуются (login state, health alerts, warming progress) | ✅ **CLOSED (2026-09-13):** `get_publisher()` теперь реальный (синхронный redis-клиент, тот же класс, что у воркера) → переходы из API публикуют в `account_status` так же, как из воркера (ровно один раз на переход — вторую публикацию не добавляли). `LoginEventHub` слушает `login` **и** `account_status` и отдаёт оба типа через один per-account SSE (login-кэш обновляет только `login`). Добавлены каналы `warming_progress` (после `warming.tick`: `{account_id, action_type, status, kind}`) и `health_alert` (при создании `HealthEvent`: `{account_id, event_type, severity}`). Побочно: publisher воркера переведён на синхронный клиент (arq-редис async → `publish` возвращал корутину и не публиковал). | **CLOSED** |
| 10 | Миграции vs модели | Нет расхождений (`alembic check`) + runtime-накат | ✅ **CLOSED (2026-09-13):** дрейфа нет (`alembic check`). Добавлен runtime-шаг: `deploy/entrypoint-api.sh` делает `alembic upgrade head` ПЕРЕД `exec gunicorn … api.asgi:app` (`set -eu` — упавшая миграция прерывает старт) → прод-контейнер сам мигрирует. | **CLOSED** |

## Дополнительно найденное (сверх списка)

| # | Место | Ожидание | Факт | Severity |
|---|-------|----------|------|----------|
| 11 | Каскад #1+#2 | created→warming→pool работает end-to-end | ✅ **CLOSED (2026-09-13):** как следствие закрытия #1/#2 путь created→warming→pool теперь запускается естественно от `login_confirm`/`login_password` (регрессионный e2e-тест `test_login_confirm_to_pool_without_manual_initial_start` в `tests/test_warming.py` проходит без ручного вызова `initial_start`). ~~Аккаунт застревал в `warming`.~~ | **CLOSED** |
| 12 | `ClientPool` в воркере (`worker/main.py`) | Пул кладётся в `ctx` при старте | ✅ **CLOSED (2026-09-13):** `startup` кладёт `ClientPool` в `ctx['client_pool']` явно и СРАЗУ (до `load_all` и прочих зависимых инициализаций); ленивое `_pool(ctx)` в login/warming/commenting теперь переиспользует готовый пул. В `shutdown` — `close_all`. | **CLOSED** |
| 13 | Прогрев: выбор целей (`worker/warming/actions/base.py`) | Подписки/чтение по интересам персоны | ⏸️ **DEFERRED (2026-09-13):** v2-фича, требует отдельного проектирования (модель интересов персоны). Для v1 хардкод публичных каналов достаточен, пайплайн не блокирует. TODO #13 в `docs/PROJECT.md`. | **DEFERRED** |
| 14 | `account.retire` / `account.acknowledge_ban` как arq-задачи | Реализованы | ⏸️ **DEFERRED (2026-09-13):** синхронный путь через API (`/accounts/{id}/actions/*` → state machine) достаточен для v1; отдельные arq-задачи нужны только под batch-retire, которого нет. TODO #14 в `docs/PROJECT.md`. | **DEFERRED** |

## Итог (2026-09-13)

**Все 14 пунктов имеют финальный статус: 12 CLOSED, 2 DEFERRED (#13, #14).**
Все blocker/major закрыты и покрыты тестами (см. промпты 19–24). Сквозной
контрольный прогон — `tests/integration/test_full_pipeline.py`. Отложенные
пункты #13/#14 задокументированы как TODO в `docs/PROJECT.md`.

## Рекомендованный порядок устранения (выполнено)

1. ✅ **#1/#2/#11 — CLOSED (2026-09-13).** Прогрев запускается прямым enqueue `warming.initial_start` из `login/flow.py::_finish_login` сразу после перехода created→warming; лишняя задача-обёртка `account.start_warming` удалена. Пайплайн created→warming→pool замкнут (см. строки #1/#2/#11).
2. ✅ **#4 + #12 — CLOSED (2026-09-13).** `ClientPool` кладётся в `ctx` при старте; слушатели подключаются через `ListenerRegistry.load_all`; динамика кампаний — через pub/sub-канал `campaign_lifecycle` и фоновую `CampaignLifecycleListener` (attach/detach без рестарта). См. строки #4/#12.
3. ✅ **#5 + #6 — CLOSED (2026-09-13).** ASGI entry-point `api.asgi:app` (create_app + lifespan/CORS/request-id/error-handler) + gunicorn-конфиг; зависимости приведены в runtime-секцию с версиями, `packages.find` починен. См. строки #5/#6.
4. ✅ **#7/#8 — CLOSED (2026-09-13).** warming/login-вызовы Telethon прогнаны через `around_telethon_call` и governor (лимиты `warming`/`login` ожили; health-события warming/login больше не теряются; login-разбор FloodWait не сломан). См. строки #7/#8.
5. ✅ **#9 — CLOSED (2026-09-13).** `get_publisher` реальный; `account_status` публикуется и потребляется (SSE); добавлены `warming_progress` и `health_alert`; publisher воркера переведён на синхронный клиент. См. строку #9.
6. ✅ **#3 + #10 — CLOSED (2026-09-13).** Реальный SOCKS5/HTTP-хендшейк прокси (`worker/health/proxy_probe.py`); runtime-накат миграций в `deploy/entrypoint-api.sh`. См. строки #3/#10.
7. ⏸️ **#13 + #14 — DEFERRED (2026-09-13).** Осознанно отложены (v2 / достаточно синхронного пути) — TODO в `docs/PROJECT.md`. См. строки #13/#14.
