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

## Этап 7. Безопасность

### Recovery-email flow при set_2fa
* **Триггер:** когда в mini-app появится страница управления 2FA.
* **Что:** сейчас `email` кладётся в payload, но Telethon `edit_2fa` при первом
  вызове с email требует code_callback (пришедший email-код) → в фоне это
  сломает bulk. Решение: отдельный вход-flow «attach recovery email» с двумя
  задачами: `security.request_email_code` (кладёт code_hash в meta) →
  `security.confirm_email_code` (вводит код, дожёвывает 2FA). MVP пока
  игнорирует email в bulk — оставляем в payload на будущее.

---

## Этап 8. Каналы и чаты

### Bulk-действие «сгенерировать канал»
* **Триггер:** когда пользователь попросит массово создавать проектные каналы.
* **Что:** action `create_channel` (`channels.CreateChannelRequest`), после —
  `PinMessageRequest` на первом посте. Пожалуй, требует отдельного
  ``project_channels`` учёта, чтобы не потерять созданные каналы.

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

## Прочее (кросс-этапное)

### Формализовать triggered_status_change как enum
* **Из:** [PROJECT.md](../PROJECT.md) — TODO по моделям.
* **Триггер:** когда появится агрегация по этому полю в дашборде/аналитике.

### CHECK на account.previous_status
* **Из:** [PROJECT.md](../PROJECT.md) — TODO по моделям.
* **Триггер:** при первом инциденте с «мусорным» значением в поле.
