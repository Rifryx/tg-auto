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

---

## [E3.1] Folder-links (`t.me/addlist/...`, `t.me/list/...`)

**Статус:** классификатор `classify_channel_input` относит такие ссылки
к `kind='folder'` и БД хранит их, но резолвер (папка → набор чатов)
не реализован. В UI показываем «распознан пак-каналов, но пока не
поддерживается».

**Что должно делать:**
- Через прогретый MTProto-клиент вызывать
  `client(chatlists.CheckChatlistInviteRequest(slug=...))`, получать
  список чатов, автоматически подписываться на каждый (уважая delay-пресеты),
  создавать по одному `CampaignChannel` с `kind='username'` и уже
  резолвленным `resolved_chat_id`.

**Что писать:**
1. Модуль `modules/commenting/worker/channel_resolver.py`:
   - `resolve_folder(client, slug: str) -> list[ResolvedChat]`,
   - `resolve_username(client, ref: str) -> ResolvedChat | None`,
   - `resolve_invite(client, hash_: str) -> ResolvedChat | None`.
2. Таск `commenting.resolve_campaign_channel` (per raw_input), enqueue
   при создании `CampaignChannel` и по расписанию для `last_error != NULL`.

**Важные детали:**
- `checkChatlistInvite` требует, чтобы аккаунт-резолвер сам был
  прогретым и с адекватным DC. На cold-аккаунте — FloodWait / PEER_ID_INVALID.
- Некоторые slug'и содержат приватные чаты — не подписываемся молча,
  UI должен спросить подтверждение.

**Где смотреть:** `modules/commenting/schemas/channel_source.py`
(`classify_channel_input`), `modules/commenting/models/channel_source.py`
(`CampaignChannel.kind`).

---

## [E3.2] Runtime целевых каналов: резолвер + not-subscribed handler + auto-blacklist

**Статус:** схема (Campaign.channel_source_mode / on_not_subscribed_action)
и CRUD целевых каналов/ЧС есть. Воркер их пока не читает.

**Что должно делать:**
1. **Резолвер** для `explicit_links`: при attach аккаунта или создании
   `CampaignChannel` подписать каждого assigned-аккаунта на канал
   (Telethon `JoinChannelRequest` для username и invite; folder → E3.1).
   Успех → заполнить `resolved_chat_id` + `title`; ошибка → `last_error`.
2. **Not-subscribed handler**: при постинге, если Telethon вернул
   `ChannelPrivateError` / `ChatWriteForbiddenError` / `UserNotParticipantError`:
   - Если `on_not_subscribed_action='subscribe_and_notify'` → попытаться
     `JoinChannelRequest`, если успех → перепланировать пост.
   - В любом случае → опубликовать событие
     `commenting.channel_unsubscribed` в Redis (см. `bot/notifier.py`)
     с полями `campaign_id, account_id, channel`.
   - Записать `CommentLog{status='flagged', error='not_subscribed'}`.
3. **Auto-blacklist**: при устойчивой ошибке доступа (`ChannelPrivate`,
   `ChatBanned`) — вставить запись в `channel_blacklist` с `auto=True` и
   `reason=<код>`. Проверять ЧС в `on_new_post` до планирования — если
   канал в ЧС, скипнуть.
4. **`by_account_subscriptions`**: игнорировать `CampaignChannel`, работать
   по существующим `MonitoredChannel` аккаунта.

**Что писать:**
1. Новый Redis-канал `commenting.channel_unsubscribed`; добавить формат
   и подписку в `bot/notifier.py::_ACCOUNT_STATUS_CHANNEL` соседом.
2. В `runner.py::on_new_post` / `on_channel_post` вызов
   `_ensure_subscribed(account_id, channel)` перед send.
3. В `worker/registry.py` — при attach прогонять resolver для
   `explicit_links` кампаний.

**Важные детали:**
- Массовая подписка со свежего аккаунта → мгновенный FloodWait. Уважать
  `campaign.join_delay_min_sec / join_delay_max_sec` (уже в БД).
- Auto-blacklist должен различать `ChannelPrivate` (навсегда, blacklist)
  и transient (`FloodWait`, `Timeout` — не blacklist).
- Пуш на «главный экран мини-аппа»: нужен отдельный in-app inbox
  (сейчас notifier шлёт только в Telegram-бота). Задел на новый модуль
  `notifications`; пока — только Telegram-пуш.

**Где смотреть:** `bot/notifier.py` (образец pub/sub-обработчика),
`modules/commenting/worker/runner.py` (точка постинга),
`modules/commenting/repositories/channel_source.py::find` (проверка ЧС).

---

## [E4.1] Стиль коммента: emojis / stickers / attach_image / write_as_channel

**Статус:** флаги `use_emojis / use_stickers / attach_image /
write_as_channel` есть в модели и API. Runtime их пока не читает.

**Что должно делать:**
- `use_emojis` (default TRUE): если FALSE — при генерации LLM просить
  не использовать эмодзи (system-подсказка `"Не используй эмодзи в ответе."`);
  дополнительно strip-эмодзи regex'ом в `style.randomize` как safety net.
- `use_stickers` (default FALSE): часть комментариев (например каждый 3-й)
  отправлять стикером из стикер-пака аккаунта вместо текста. Нужно:
  выборка стикер-паков аккаунта (`messages.getAllStickers`), кеш,
  случайный выбор пачки/стикера; `SendMessageMediaRequest`.
- `attach_image` (default FALSE): к каждому текстовому комменту
  прикладывать картинку. Источник — существующие media-assets
  (`0022_media_assets`). При отправке `send_file(message=text)`.
- `write_as_channel` (default FALSE): отправлять коммент от имени канала,
  а не своего юзера. Требует, чтобы аккаунт был админом канала с правом
  `post_messages`. Telethon: `send_message(..., send_as=<channel_input_peer>)`;
  надо предварительно получить список `send_as` через
  `channels.getSendAs`. Если разрешённых нет — тумблер игнорировать
  и залогировать warning.

**Что писать:**
1. В `runner.py::on_new_post`, перед `provider.generate`: собрать
   инструкции по флагам и подмешать в system prompt.
2. `_pick_delivery_mode(campaign, rng)`: text | sticker | text_with_image.
   Пороги — константы, MVP: sticker 25%, image 40% если флаг включён.
3. Хелпер `_send_as_target(client, campaign, account)` — определяет
   отправителя (self или channel).

**Важные детали:**
- `use_stickers` + `use_emojis=false` → противоречие только на первый
  взгляд: стикеры — не эмодзи, флаги независимы.
- `attach_image` без свободных media-assets → скипать, не падать.
- `write_as_channel` — если админ снял права после старта, `send_message`
  вернёт `ChatAdminRequiredError` → авто-выключить флаг для этой
  кампании и уведомить (см. [E3.2]).

**Где смотреть:** `modules/commenting/worker/runner.py::on_new_post`
(там формируются plans), `modules/media/assets/` (существующий пул),
`modules/commenting/models/campaign.py` (сами флаги).

---

## [E4.2] Verify-after-post seam (live-verification gate)

**Статус:** поля `verify_after_post`, `verify_delay_sec` (default 300)
есть в модели/API. Задача-«верификатор» не запланирована.

**Что должно делать:**
- Если `verify_after_post=TRUE`: после успешного `post_comment`
  запланировать `commenting.verify_comment(comment_log_id)` на
  `now + verify_delay_sec`.
- Верификатор берёт `comment_log`, читает `posted_message_id` тем же
  аккаунтом, что постил (правило who-comments из MEMORY:
  monitoring-architecture), пытается прочитать сообщение в чате
  (`get_messages(chat, ids=[posted_message_id])`).
  - Если None или исключение → пометить `CommentLog.status='flagged'`,
    `error='removed_by_moderator'`, publish в новый Redis-канал
    `commenting.comment_verified_removed`.
  - Если ok → апдейтнуть `verified_at`.

**Что писать:**
1. Новая колонка `comment_log.verified_at TIMESTAMPTZ nullable`
   (миграция + модель).
2. Таск `commenting.verify_comment` в `worker/tasks/handlers.py` и
   `TaskName.COMMENTING_VERIFY_COMMENT`.
3. Планирование в `runner.py::post_comment` при
   `campaign.verify_after_post` and post success.
4. Reply-to-human-comment seam (future) — та же задача,
   позже расширяется по MEMORY.

**Важные детали:**
- Тот же аккаунт: если аккаунт ушёл в cooldown/banned за это время —
  скипнуть верификацию и залогировать `verify_skipped_stale_account`.
  Не переключать на другой аккаунт (это будет отдельный сигнал —
  «внешний наблюдатель», не для MVP).
- Один retry: если пост был удалён Telegram-side (rate-limit reject),
  верификатор не должен думать, что модератор снял его.

**Где смотреть:** `modules/commenting/worker/runner.py::post_comment`
(точка планирования), `modules/commenting/models/comment_log.py`
(куда добавлять `verified_at`), MEMORY `monitoring-architecture.md`
(канон правила).
