# Отложенные фичи (backlog)

Живой список того, что заложено в UI/схеме, но пока без реального
backend'а. Каждый пункт — самодостаточное ТЗ: что делает, что писать,
на какие места смотреть при возврате. Дописывать сюда всё, что уходит
в «сделаем позже», чтобы не терять контекст.

---

## [E0.2] TData → StringSession (импорт папок Telegram Desktop)

**Статус:** UI-заглушка в `frontend/src/screens/accounts/BulkImportScreen.tsx`
(drop-зона «TData» показывает подсказку «скоро»). Backend не реализован.

**Что должно делать:**
- Принимать либо ZIP-архив, либо распакованную папку `tdata` (пользователь
  перетаскивает целиком) — на бэк приходит ZIP.
- Распаковывать во временную директорию, находить внутри валидные
  `tdata`-структуры (каждая — один аккаунт), конвертировать каждую в
  Telethon StringSession.
- Дальше — как в текущем `.session`-импорте: подобрать/принять `proxy_id`,
  создать `Account`, зашифровать сессию, поставить `status = created`,
  запустить обычный warming.

**Что писать:**
1. Зависимость: `opentele` (`pip install opentele`) — единственная зрелая
   Python-библиотека для чтения tdata. Проверить лицензию (MIT).
2. Модуль `modules/accounts/importers/tdata.py`:
   - `parse_tdata_archive(zip_bytes: bytes) -> list[TDataAccount]`,
   - `TDataAccount` = `{ phone, string_session, api_id, api_hash, dc }`.
3. Расширить `accountsApi.bulkImport` (frontend) и соответствующий
   FastAPI-эндпоинт: принимать `kind: "tdata" | "session_zip" | "csv"`,
   роутить в нужный импортёр.
4. Отчёт по строкам — как у CSV-импорта (imported/skipped с причиной).
5. Отдельная миграция не нужна: используется существующая таблица `accounts`.

**Важные детали:**
- TData содержит **live-сессию** — импорт мгновенно "оживляет" аккаунт
  без SMS. Поэтому обязательно требовать привязку `proxy_id` **до**
  создания клиента; иначе первый connect уйдёт с сервера и спалит аккаунт.
- В tdata иногда лежит несколько DC-ключей — брать только основной.
- Пароль 2FA в tdata **не хранится** (только session-ключ) — если у
  аккаунта включён 2FA и пароль неизвестен, при `SessionRevoked` мы
  ничего не восстановим. Показать это предупреждение в UI до импорта.
- Одна tdata-папка = один аккаунт. Пакетный tdata (несколько папок в
  одном ZIP) — вторая итерация, не MVP этой фичи.
- Файлы tdata содержат приватные ключи — временную распаковку делать
  в `tempfile.TemporaryDirectory()`, гарантированно чистить в `finally`.

**Где смотреть при возврате:**
- Заглушка UI: `frontend/src/screens/accounts/BulkImportScreen.tsx` —
  секция `TDataDropZone` с TODO-комментарием.
- Существующий `.session`-импорт (образец потока): `modules/accounts/service.py`
  функция `import_session_string` (если её нет — искать по `StringSession(`).
- Шифрование сессий: тот же контур, что уже используется для `.session`.

---

## [E2.1] Backfill существующих постов (`post_scope='existing' | 'mixed'`)

**Статус:** поле `campaigns.post_scope` есть в схеме и API (миграция 0028),
но воркер обрабатывает только новые посты (listener). Значения `existing`
и `mixed` пока эквивалентны `new`.

**Что должно делать:**
- Одноразовый (или разовый на кампанию/канал) проход по истории привязанных
  каналов: скачать последние N постов, для каждого прогнать тот же фильтр
  отбора (keywords/probability), поставить `commenting.on_new_post` с
  повышенным лимитом задержки (не постить сразу всю пачку — раскидать по
  «Настройке задержек»).
- `mixed` = сначала backfill, потом обычный listener (уже работает).

**Что писать:**
1. Новая worker-задача `commenting.backfill_channel` (aiogram/telethon
   `iter_messages(channel, limit=BACKFILL_LIMIT)`), лимит вынести в
   `core.config`.
2. Триггер: при создании кампании с `post_scope in ('existing', 'mixed')`
   и при `PATCH` этого поля → publish `backfill.requested` в очередь.
3. Дедуп по `CommentLog` — не постить дважды на один `channel_msg_id`.
4. Соблюдать `active_hours` и все delay-пресеты (текущий `on_new_post`
   уже соблюдает — переиспользовать).

**Важные детали:**
- Telegram лимитирует историю: без прогретого аккаунта `iter_messages`
  на 1000 сообщений подряд гарантированно словит FloodWait — брать
  порционно (100), между порциями `asyncio.sleep(60..120)`.
- `existing` без явного лимита = «все посты канала» → на большом канале
  сотни задач. Ввести hard-cap (например 200 постов).

**Где смотреть:** `modules/commenting/worker/listener.py` (там сейчас
только «новые»), `modules/commenting/worker/runner.py::on_new_post`
(для reuse дозирования и delay), таблица `commenting.comment_log`
для дедупа.

---

## [E2.2] Лимиты работы: `max_comments`, `min_words`, окно и пауза

**Статус:** поля `work_mode / max_comments / min_words /
window_after_post_sec / pause_between_sec` есть в модели и API, но
runner их пока не читает — лимиты не применяются.

**Что должно делать:**
- `work_mode='by_count'`: перед постингом каждого коммента считать
  `SELECT count(*) FROM comment_log WHERE campaign_id=? AND status='posted'`;
  если ≥ `max_comments` → скипнуть, залогировать `limit_reached`.
- `min_words`: считать слова в тексте, сгенерированном LLM; если меньше
  порога — regenerate (2 попытки максимум), иначе скипнуть с
  `status='failed', error='below_min_words'`.
- `work_mode='by_time_window'`: игнорировать пост, если
  `now - message.date > window_after_post_sec`; между комментариями
  соблюдать `pause_between_sec` (per-account cooldown, хранится в Redis
  или в новой таблице `campaign_account_state`).

**Что писать:**
1. Функция `_check_campaign_limits(session, campaign, account_id)` в
   `runner.py`, вызывать в `on_new_post` перед формированием plans.
2. Retry-loop `min_words` в `_generate_and_style` (2 попытки).
3. Per-account cooldown — простейший вариант: доп. поле
   `campaign_accounts.last_posted_at TIMESTAMPTZ` (новая колонка +
   миграция); проверять `now - last_posted_at < pause_between_sec`.

**Важные детали:**
- Считать по `posted`, а не по `attempts`: неуспешные не должны съедать
  лимит.
- Окно `by_time_window`: `message.date` — это дата ПУБЛИКАЦИИ поста
  канала, а не приёма события (event.date может быть позже, если
  handler переподключался).

**Где смотреть:** `modules/commenting/worker/runner.py::on_new_post` (там
формируются plans), `modules/commenting/models/comment_log.py`
(для агрегата), `modules/commenting/models/campaign_account.py`
(куда добавлять `last_posted_at`).
