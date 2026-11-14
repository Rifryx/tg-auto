/** Русские формулировки кодов ошибок/пропусков bulk-действий.
 *
 * Бэкенд кладёт в item.error технический код (``premium_required``,
 * ``no_persona`` и т.п.). Пользователю показываем по-русски, без английского.
 * Неизвестный код оборачиваем в нейтральное русское сообщение (сам код
 * оставляем в скобках — помогает поддержке, но интерфейс остаётся русским).
 */
const BULK_ERROR_RU: Record<string, string> = {
  premium_required: "Нужен Telegram Premium",
  stories_limit: "Достигнут лимит историй на сегодня",
  account_missing: "Аккаунт не найден",
  account_gone: "Аккаунт удалён",
  account_not_found: "Аккаунт не найден",
  not_found: "Не найдено",
  no_account: "Нет аккаунта",
  no_persona: "У аккаунта нет персоны",
  persona_missing: "Персона не найдена",
  generation_failed: "Не удалось сгенерировать профиль",
  no_avatar: "Нет аватара",
  empty_pool_match: "В пуле нет подходящего ассета",
  no_source: "Нет исходных данных",
  media_asset_not_found: "Медиа не найдено",
  media_not_found: "Медиа не найдено",
  thumb_asset_not_found: "Превью не найдено",
  not_data_url: "Неверный формат изображения",
  empty_blob: "Пустой файл",
  empty_payload: "Пустой запрос",
  bad_period: "Недопустимый срок",
  video_attributes_required: "Нужны параметры видео",
  no_proxy_left: "Нет свободного прокси",
  proxy_not_found: "Прокси не найден",
  no_proxy: "Нет прокси",
  channel_resolve_failed: "Не удалось определить канал",
  resolve_failed: "Не удалось определить цель",
  no_channel_in_response: "Канал не создан",
  already_created: "Уже создано",
  pin_failed: "Не удалось закрепить",
  need_current_password: "Нужен текущий пароль",
  new_password_required: "Нужен новый пароль",
  cannot_decrypt_current: "Не удалось расшифровать текущий пароль",
  invalid_current_password_enc: "Неверный текущий пароль",
  invalid_password_enc: "Неверный пароль",
  deferred: "Отложено",
};

export function bulkErrorRu(raw: string | null | undefined): string {
  const s = (raw ?? "").trim();
  if (!s) return "Ошибка";
  // Точное совпадение по коду.
  if (BULK_ERROR_RU[s]) return BULK_ERROR_RU[s];
  // Код с деталью после разделителя: «generation_failed: ...».
  const head = s.split(/[:\s]/, 1)[0];
  if (BULK_ERROR_RU[head]) {
    const tail = s.slice(head.length).replace(/^[:\s]+/, "").trim();
    return tail ? `${BULK_ERROR_RU[head]}: ${tail}` : BULK_ERROR_RU[head];
  }
  // Уже человекочитаемая строка (есть кириллица/пробелы) — показываем как есть.
  if (/[А-Яа-яЁё]/.test(s) || s.includes(" ")) return s;
  // Неизвестный технический код — нейтральная русская обёртка.
  return `Ошибка (${s})`;
}
