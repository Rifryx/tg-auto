/* Перевод технических кодов ошибок Telegram/Telethon на русский — для показа
 * в UI. В БД ошибка хранится как есть (имя исключения Telethon: PeerFloodError,
 * SlowModeWaitError… или наш код slow_mode_wait:30s) — удобно для отладки, но в
 * интерфейсе не должно торчать английскими словами. Переводим ТОЛЬКО при показе,
 * неизвестное отдаём как есть (без хвоста «…Error»). */

const EXACT: Record<string, string> = {
  PeerFloodError: "слишком много действий — Telegram придержал аккаунт",
  FloodWaitError: "флуд-контроль Telegram — нужно подождать",
  SlowModeWaitError: "медленный режим в чате — ждём",
  ChatWriteForbiddenError: "в этот чат писать нельзя",
  ChatSendMediaForbiddenError: "в этот чат нельзя отправлять медиа",
  ChannelPrivateError: "чат приватный или удалён",
  UserBannedInChannelError: "аккаунт забанен в этом чате",
  UserDeactivatedError: "аккаунт удалён",
  UserDeactivatedBanError: "аккаунт заблокирован",
  ChatAdminRequiredError: "нет прав писать в этот чат",
  UserNotParticipantError: "аккаунт не состоит в чате",
  UserPrivacyRestrictedError: "настройки приватности пользователя не позволяют",
  AuthKeyUnregisteredError: "сессия аккаунта недействительна",
  SessionRevokedError: "сессия аккаунта отозвана",
  SessionExpiredError: "сессия аккаунта истекла",
  MsgIdInvalidError: "сообщение, на которое отвечаем, недоступно",
  MessageNotModifiedError: "сообщение не изменилось",
  UsernameInvalidError: "недопустимый username",
  UsernameOccupiedError: "username занят",
  PhoneNumberBannedError: "номер заблокирован в Telegram",
};

/** Переводит код ошибки Telegram в понятную русскую фразу. Неизвестное — как есть. */
export function humanizeTgError(raw: string | null | undefined): string {
  if (!raw) return "";
  const s = raw.trim();

  // Коды с параметром: «slow_mode_wait:30s», «slow_mode_too_long:600s»,
  // «replaced_by:42», «flood_wait:30s».
  const slowWait = s.match(/^slow_mode_wait:(\d+)s$/);
  if (slowWait) return `медленный режим в чате — ждём ${slowWait[1]} c`;
  const slowLong = s.match(/^slow_mode_too_long:(\d+)s$/);
  if (slowLong)
    return `медленный режим дольше лимита (${slowLong[1]} c) — шаг пропущен`;
  const flood = s.match(/^flood_wait:(\d+)s?$/i);
  if (flood) return `флуд-контроль Telegram — ждём ${flood[1]} c`;
  if (/^replaced_by:\d+$/.test(s)) return "заменён резервным аккаунтом";

  if (EXACT[s]) return EXACT[s];
  // Прочие *Error от Telethon: показываем без английского «…Error» хвоста.
  if (/Error$/.test(s)) return `ошибка Telegram (${s.replace(/Error$/, "")})`;
  return s;
}
