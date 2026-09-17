# Stages backlog — отложенные пункты по этапам

Хранит всё, что осознанно вынесено «на потом» из основных этапов (Account Manager
+ УТП: живые аккаунты, anti-ban predictor, автопилот). Каждый пункт: короткое
название, откуда возник, что делать, когда лучше делать.

Правила ведения:
* Никаких tombstone'ов «сделано» — если пункт закрыт, удалить из файла.
* Каждый пункт содержит **этап-владелец** и **триггер** (когда возвращаться).
* Пункты, тесно связанные с ещё не начатым этапом, кладём под его будущий раздел
  (Backlog by stage) — не размазываем по всему файлу.

---

## Этап 4. Health-check и Health Score

### Тест reactive-пути на уровне check_account_impl
* **Триггер:** при первом рефакторинге `worker/tasks/health.py::check_account_impl`.
* **Что:** сейчас юнит-тесты `probe_session` покрывают реактивный путь напрямую;
  интеграционного теста «check_account_impl завершил акк как banned» нет — есть
  только моковый вариант. Добавить, чтобы обкатать `client_pool.get` + probe
  вместе.

---

## Этап 5. Bulk Actions

### Governor на bulk-item
* **Триггер:** когда появится массовое действие, которое бьёт по Telegram API
  часто (комментинг/публикация Stories).
* **Что:** перед вызовом `action.run(...)` в `worker/tasks/bulk.py::item_impl`
  зарезервировать слот через `Governor.check_and_reserve(account_id, action_type)`
  где `action_type` мапится из `BulkActionType` (напр. `comment`, `warming`).
  Если слот не выдан — item помечается `pending` заново и re-enqueue через
  `TaskQueue.schedule(now + backoff)`.
* **Зависимость:** `worker.health.governor.LIMITS` — расширить мапой на
  `BulkActionType`.

### UI-формы под payload действий
* **Триггер:** этап 13 (Mini-app UX) — когда откроется экран bulk-операций.
* **Что:** каждое действие в `modules/bulk/actions/*` уже описывает свою
  `payload_schema` (pydantic). Нужен API-эндпоинт `GET /bulk-jobs/actions`,
  который отдаёт: `name`, `title`, `description`, `requires_client`, и
  JSON-schema payload'а (`payload_schema.model_json_schema()`). Mini-app по этому
  генерирует форму.

### assign_proxy как bulk-action
* **Триггер:** после этапа 3 (Пул прокси).
* **Что:** массовое переназначение прокси с соблюдением инв. §4 (один прокси =
  один аккаунт, гео совпадает). Не тривиально: нужна логика захвата/освобождения
  прокси из пула, учёт гео номера, обработка «прокси кончились в пуле» → item
  идёт в SKIPPED с причиной.

---

## Этап 7. Безопасность

### Recovery-email flow при set_2fa
* **Триггер:** когда в mini-app появится страница управления 2FA.
* **Что:** сейчас `email` кладётся в payload, но Telethon `edit_2fa` при первом
  вызове с email требует code_callback (пришедший email-код) → в фоне это
  сломает bulk. Решение: отдельный вход-flow «attach recovery email» с двумя
  задачами: `security.request_email_code` (кладёт code_hash в meta) →
  `security.confirm_email_code` (вводит код, дожёвывает 2FA). MVP пока
  игнорирует email в bulk — оставляем в payload на будущее.

### Ротация ключа шифрования
* **Триггер:** плановая ротация ENCRYPTION_KEY.
* **Что:** сейчас Fernet-инстанс кешируется по строке ключа. Для ротации нужно
  поддержать список ключей (первый — для write, все — для read) в
  `core/crypto/fernet.py::_get_fernet`, чтобы старые blob'ы читались, а новые
  писались новым ключом. Обычно `MultiFernet`.

---

## Этап 8. Каналы и чаты

### Реюз helper'ов в commenting-модуле
* **Триггер:** следующий touch файла `modules/commenting/worker/channels.py`.
* **Что:** после этапа 8 экстрактнутые парсеры лежат в
  `worker/telegram_refs.py` (`strip_url`, `folder_slug`, `invite_hash`,
  `public_ref`, `classify_ref`). В `commenting/worker/channels.py` остались
  локальные копии — заменить на импорт из worker.telegram_refs. Ничего не
  ломается сейчас (обе версии идентичны), но при следующей правке одной из
  двух будет дрейф — лучше свернуть заранее.

### Bulk-действие «сгенерировать канал»
* **Триггер:** когда пользователь попросит массово создавать проектные каналы.
* **Что:** action `create_channel` (`channels.CreateChannelRequest`), после —
  `PinMessageRequest` на первом посте. Пожалуй, требует отдельного
  ``project_channels`` учёта, чтобы не потерять созданные каналы.

### Bulk-действие «поставить реакцию»
* **Триггер:** когда в mini-app появится «реакция-boost» под пост.
* **Что:** action `send_reactions` (`messages.SendReactionRequest`) на набор
  ссылок постов. Payload: `{post_urls, emoji}`. Rate-limit governor обязателен —
  реакции быстро палятся антифродом.

### Bulk view + folders
* **Триггер:** когда развернём папки addlist как first-class объект.
* **Что:** сейчас `join_channels` возвращает `folders_unsupported_in_bulk` для
  ссылок addlist. Логику разворачивания в дочерние каналы можно взять из
  `commenting/worker/channels.py::_resolve_folder`, но без записи в
  `monitored_channels` — только фактическое присоединение.

---

## Этап 9. Stories

### Media store вместо base64 в payload
* **Триггер:** первый реальный юзкейс с картинкой > 200 КБ.
* **Что:** сейчас ``publish_story.payload.media_b64`` — base64 в JSONB. Для
  1080×1920 фото это ~1–2 МБ на job (payload шарится между item'ами — не
  умножается на N аккаунтов, но всё равно тяжело). Решение: таблица
  ``media_assets`` (id, mime, bytes, sha256, created_at) + ``media_asset_id`` в
  payload. Плюсом можно шарить одну картинку между несколькими story-job'ами.

### Video / документ в Stories
* **Триггер:** когда пользователь попросит видео-Stories.
* **Что:** сейчас поддерживаем только ``InputMediaUploadedPhoto``. Для видео
  нужна ``InputMediaUploadedDocument`` с video-attributes (duration/w/h) и
  превью-thumbnail; работает через тот же ``upload_file``, но с обработкой
  больших файлов (несколько частей, MTProto file references).

### Расписание публикаций
* **Триггер:** этап 10/12 (Warmup Engine / Autopilot).
* **Что:** сейчас ``publish_story`` шедулится через arq по расписанию извне.
  Хочется параметр ``scheduled_at`` в payload → task сама через
  ``TaskQueue.schedule`` откладывает execute. Пока Autopilot не построен —
  проще пользоваться внешним крон-планировщиком.

---

## Этап 10. Warmup Engine

### Persona-based targets в warming actions
* **Триггер:** первая жалоба «все аккаунты подписаны на @telegram/@durov».
* **Что:** ``worker/warming/actions/*.py`` (7 файлов) сейчас берут target из
  константы ``DISCOVERY_CHANNELS``/``DISCOVERY_GROUPS``. Надо: helper
  ``pick_target(rng, persona, kind)`` — читает ``persona.interests`` (если не
  пусто), fallback на константы. Действие получает persona через декоратор
  ``@action`` (расширить сигнатуру ``execute(client, account, persona=None)``).

### Trust-graph: действие ``interact_with_peer``
* **Триггер:** когда persona-targets свернутся и не будет других приоритетов.
* **Что:** новое ``WarmingActionType.INTERACT_WITH_PEER``. Реализация: находим
  всех аккаунтов с тем же ``persona_id`` (или той же commenting-кампанией),
  случайный peer у которого есть публичный username, читаем историю его
  общения на общем канале / ставим реакцию. Требует миграции ``warming_activities``
  (расширить CHECK ``action_type``) и обновления enum. Даст УТП второй уровень:
  «аккаунты одного проекта естественно живут вместе».

### Scheduler tick с ошибкой не должен зависать
* **Триггер:** первый прод-инцидент с ChatWriteForbidden в прогреве.
* **Что:** ``execute_action`` ловит все Exception → item ``failed``. Некоторые
  ошибки (``ChatWriteForbidden`` при подписке на закрытый канал) — семантически
  «повторим на другом канале», а не «прогрев акка сломан». Отдельная категория
  ошибок в ``WarmingActionResult.meta``.

---

## Этап 3. Пул прокси (ещё не начат)

_Пока пусто — заведу пункты при старте этапа._

---

## Этап 6. Оформление профилей

### Пул asset'ов (аватарки / имена / био / username-шаблоны)
* **Триггер:** когда добавим ручной bulk-режим оформления «без LLM».
* **Что:** таблица `profile_assets` (`kind: avatar/first_name/last_name/bio/username_template`,
  `value` / `binary_url`, `tags` JSONB, `used_count`). API CRUD; bulk-action
  `apply_profile_pool` рандомно берёт asset'ы по kind + фильтру тегов.
  Сейчас в этапе 6 сделан только AI-путь (`generate_and_apply_profile`).

### Загрузка аватара из URL/файла в Telegram
* **Триггер:** когда появится пул asset'ов ИЛИ когда генератор начнёт возвращать
  референсную картинку.
* **Что:** helper в `worker/profiles/apply.py::upload_avatar` — скачать медиа
  (aiohttp через прокси аккаунта!) → `client.upload_file` → `SetProfilePhoto`.
  Учесть: клиент акка ходит через свой прокси, а вот скачивание внешнего URL —
  нет; нужно решать, из какой сети скачивать (риск раскрытия IP серверной).

### Асинхронная валидация username-кандидатов из LLM
* **Триггер:** когда bulk `generate_and_apply_profile` начнёт часто натыкаться на
  занятые username'ы.
* **Что:** после генерации LLM прогонять `probe_username(candidate)` через
  Telethon `CheckUsernameRequest` (worker), выбирать первый свободный. Сейчас
  генератор просто отдаёт список кандидатов, а `apply_profile` применяет первый.

---

## Прочее (кросс-этапное)

### Формализовать triggered_status_change как enum
* **Из:** [PROJECT.md](../PROJECT.md) — TODO по моделям.
* **Триггер:** когда появится агрегация по этому полю в дашборде/аналитике.

### CHECK на account.previous_status
* **Из:** [PROJECT.md](../PROJECT.md) — TODO по моделям.
* **Триггер:** при первом инциденте с «мусорным» значением в поле.
