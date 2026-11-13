/* Единый список IANA-таймзон для выпадающих списков (настройки, прайминг,
   кампании). Раньше дублировался по экранам — свели в один источник. */
export const TZ_OPTIONS = [
  "UTC",
  "Europe/Kaliningrad",
  "Europe/Moscow",
  "Europe/Kyiv",
  "Europe/Minsk",
  "Europe/London",
  "Europe/Berlin",
  "Europe/Istanbul",
  "Asia/Yekaterinburg",
  "Asia/Almaty",
  "Asia/Novosibirsk",
  "Asia/Tashkent",
  "Asia/Dubai",
  "Asia/Tbilisi",
  "Asia/Yerevan",
  "America/New_York",
  "America/Chicago",
  "America/Los_Angeles",
];

/** Таймзона браузера пользователя (или пустая строка, если недоступна). */
export function detectedTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch {
    return "";
  }
}
