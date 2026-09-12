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
| 1 | `account.start_warming` (`worker/tasks/handlers.py`) | После `login_confirm`/`login_password` переход created→warming ставит задачу запуска прогрева | Задача — **заглушка** в `_STUB_TASKS` (кидает `NotImplementedError`) и **никем не enqueue'ится**. `login/flow.py::_finish_login` делает `WARMING_START` напрямую через state machine, задачу не ставит | **blocker** |
| 2 | `warming.initial_start` (`worker/tasks/warming.py:197`) | Вызывается из `account.start_warming`, планирует стартовую пачку `warming.tick` | Функция определена, но **не вызывается ниоткуда** (только в тестах), не зарегистрирована как задача. Следствие: для аккаунтов в `warming` `warming.tick` **не ставится никогда** (`maintenance_scheduler` берёт только `pool`) → аккаунт не набирает действий → не доходит до `pool` | **blocker** |
| 3 | `health.check_proxies` (`worker/tasks/health.py:34`) | Реальный SOCKS5/HTTP-хендшейк (проверка, что прокси реально проксирует, с авторизацией) | Реализован `socket.create_connection((host, port))` — **простой TCP-connect**, не заглушка, но и не хендшейк: не проверяет тип прокси, авторизацию и фактическое проксирование | **major** |
| 4 | Регистрация NewMessage-слушателей (`modules/commenting/worker/listener.py`) | При старте воркера подключаются слушатели для всех enabled-кампаний; динамика при create/enable/disable | `start_listeners` определён, но **не вызывается в `worker/main.py`** (в `startup` его нет). Плюс требует `ctx['client_pool']`, который main тоже не кладёт. Динамики нет: функция одноразово читает кампании в момент вызова (а вызова нет). Итог: `commenting.on_new_post` из реальных событий **не приходит никогда**; изменения кампаний после старта — только рестарт (и то не помогает, т.к. вызова нет) | **blocker** |
| 5 | Entry-point API (`api/main.py`) | Запускаемый сервер (uvicorn/gunicorn, host/port/workers из конфига) | Только `app = FastAPI()`; **ни `uvicorn`/`__main__`, ни ASGI-раннера**. Способа поднять API в проде нет | **blocker** |
| 6 | Зависимости (`pyproject.toml`) | Все runtime-импорты объявлены с версиями | `httpx` используется в рантайме (`worker/llm/deepseek.py`), но объявлен **только в `dev`** → в проде DeepSeek упадёт на импорте. `google-generativeai` (`worker/llm/gemini.py`, ленивый импорт) **не объявлен нигде** → Gemini упадёт. `redis` импортируется напрямую (`api/services/*`, `api/routers/monitoring.py`), но в deps **не объявлен** (тянется транзитивно через `arq`). `uvicorn`/`gunicorn` — не объявлены и не используются (см. #5). Явно неиспользуемых объявленных зависимостей не найдено | **major** |
| 7 | `Governor` (`worker/health/governor.py`) | `check_and_reserve` вызывается из **всех** исходящих действий в Telegram (warming, posting, login) | Вызывается **только** в `commenting/worker/runner.py::post_comment` (`action_type='comment'`). В warming-действиях, `warming.tick` и логине governor **не используется** → лимиты `warming`/`login` из конфига мертвы | **major** |
| 8 | `around_telethon_call` (`worker/health/monitor.py`) | Оборачивает **все** реальные вызовы Telethon (warming, login, posting) | Используется **только** в `post_comment`. Warming-действия зовут `client(...)` напрямую (ловится лишь action-декоратором → `status=failed`, но `HealthEvent`/cooldown НЕ создаются). Логин (`send_code_request`/`sign_in`) не обёрнут (свой разбор FloodWait→reschedule, но без `HealthEvent`/cooldown на spam/ban/session_revoked) | **major** |
| 9 | Redis pub/sub | Все события для API публикуются (login state, health alerts, warming progress) | `login` — публикуется воркером (`login/flow.py`), потребляется `LoginEventHub` → **работает**. `account_status` — публикуется state machine, но **ни один API-потребитель не подписан** (`LoginEventHub` слушает только `login`); вдобавок `api/deps/queue.py::get_publisher()` возвращает **`None`**, поэтому переходы, инициированные из API (attach/detach, retire, acknowledge_ban), не публикуют вообще ничего. `warming progress` — **канала/публикации нет**. `health alerts` — pub/sub нет, только запись в БД (мониторинг опрашивает БД) | **major** |
| 10 | Миграции vs модели | Нет расхождений (`alembic check`) | `alembic check` против тестовой БД (head 0002): **«No new upgrade operations detected»** — дрейфа нет. Оговорка: dev-БД мигрируется только вручную (нет runtime-шага `alembic upgrade`; авто-накат только в тестовом conftest) | **minor** |

## Дополнительно найденное (сверх списка)

| # | Место | Ожидание | Факт | Severity |
|---|-------|----------|------|----------|
| 11 | Каскад #1+#2 | created→warming→pool работает end-to-end | После логина аккаунт «живой» в `warming`, но **никогда не переходит в `pool`** → у кампаний нет `assigned`-кандидатов (attach требует `pool`) → весь commenting-раннер в проде вхолостую. Это следствие #1/#2, но именно оно делает продукт нерабочим | **blocker** |
| 12 | `ClientPool` в воркере (`worker/main.py`) | Пул кладётся в `ctx` при старте | В `startup` `client_pool` не кладётся. Login/warming/commenting создают его лениво (`_pool(ctx)` + кэш в `ctx`, переживающем процесс) — функционально ок, НО `start_listeners` рассчитывает на готовый `ctx['client_pool']` | **minor** |
| 13 | Прогрев: выбор целей (`worker/warming/actions/base.py`) | Подписки/чтение по интересам персоны | Хардкод `DISCOVERY_CHANNELS = ("telegram","durov","tginfo")` — плейсхолдер, каталога по интересам персоны нет | **minor** |
| 14 | `account.retire` / `account.acknowledge_ban` как arq-задачи | Реализованы | Как **задачи-заглушки** (`_STUB_TASKS`). Функционально работают через API `/accounts/{id}/actions/*` (синхронно, через state machine), но задачи очереди — пустышки | **minor** |

## Рекомендованный порядок устранения (для планирования, не выполнено)

1. **#1/#2/#11** — реализовать `account.start_warming` (created→warming + enqueue `warming.initial_start`) и вызвать `start_warming` из `login/flow.py::_finish_login` (или подписаться на `WARMING_START`). Без этого пайплайн мёртв.
2. **#4 + #12** — вызывать `start_listeners` в `worker/main.py::startup`, положить `ClientPool` в `ctx`; продумать динамику кампаний.
3. **#5 + #6** — добавить ASGI entry-point и привести зависимости (`httpx`, `google-generativeai`, `redis`, `uvicorn`) в runtime-секцию с версиями.
4. **#7/#8** — прогнать warming/login-вызовы Telethon через `around_telethon_call` и governor.
5. **#9** — определить, какие каналы pub/sub реально нужны API, и включить публикацию (в т.ч. `get_publisher` в API).
