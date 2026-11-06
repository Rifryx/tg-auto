/* Перевод технических кодов ошибок отправки (execution_log.error) на русский.
 *
 * В БД ошибка хранится как есть — имя исключения Telethon (PeerFloodError,
 * SlowModeWaitError…) или наш код (slow_mode_wait:30s, replaced_by:42). Это
 * удобно для отладки, но в UI пользователь видел английские слова посреди
 * русского интерфейса. Переводим ТОЛЬКО при показе. */

const EXACT: Record<string, string> = {
  PeerFloodError: "слишком много действий — Telegram придержал аккаунт",
  FloodWaitError: "флуд-контроль Telegram — нужно подождать",
  SlowModeWaitError: "медленный режим в чате — ждём",
  ChatWriteForbiddenError: "в этот чат писать нельзя",
  ChannelPrivateError: "чат приватный или удалён",
  UserBannedInChannelError: "аккаунт забанен в этом чате",
  UserDeactivatedError: "аккаунт удалён",
  UserDeactivatedBanError: "аккаунт заблокирован",
  ChatAdminRequiredError: "нет прав писать в этот чат",
  UserNotParticipantError: "аккаунт не состоит в чате",
  AuthKeyUnregisteredError: "сессия аккаунта недействительна",
  MsgIdInvalidError: "сообщение, на которое отвечаем, недоступно",
};

/** Переводит код ошибки отправки в понятную фразу. Неизвестное — как есть. */
export function humanizeShillingError(raw: string | null | undefined): string {
  if (!raw) return "";
  const s = raw.trim();

  // Коды с параметром: «slow_mode_wait:30s», «slow_mode_too_long:600s»,
  // «replaced_by:42».
  const slowWait = s.match(/^slow_mode_wait:(\d+)s$/);
  if (slowWait) return `медленный режим в чате — ждём ${slowWait[1]} c`;
  const slowLong = s.match(/^slow_mode_too_long:(\d+)s$/);
  if (slowLong)
    return `медленный режим дольше лимита (${slowLong[1]} c) — шаг пропущен`;
  if (/^replaced_by:\d+$/.test(s)) return "заменён резервным аккаунтом";

  if (EXACT[s]) return EXACT[s];
  // Прочие *Error от Telethon: показываем без английского «…Error» хвоста,
  // чтобы не пугать, но оставить зацепку (это лучше голого класса).
  if (/Error$/.test(s)) return `ошибка Telegram (${s.replace(/Error$/, "")})`;
  return s;
}
