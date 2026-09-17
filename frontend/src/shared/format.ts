/* Форматтеры отображения. */

/** Маскирует номер: +38 050 123 45 67 → +38***4567 (не светим номер целиком). */
export function maskPhone(phone: string): string {
  const digits = phone.replace(/[^\d+]/g, "");
  if (digits.length <= 6) return digits;
  const head = digits.slice(0, 3);
  const tail = digits.slice(-4);
  return `${head}***${tail}`;
}

/** Маскирует хост прокси: 10.20.30.40 → 10.20.***.40, dom.example → do***le. */
export function maskHost(host: string): string {
  if (/^\d+\.\d+\.\d+\.\d+$/.test(host)) {
    const parts = host.split(".");
    return `${parts[0]}.${parts[1]}.***.${parts[3]}`;
  }
  if (host.length <= 4) return host;
  return `${host.slice(0, 2)}***${host.slice(-2)}`;
}

const DATE_FMT = new Intl.DateTimeFormat("ru-RU", {
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

export function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : DATE_FMT.format(d);
}

/** Относительное «N мин/ч/дн назад» для компактных лент. */
export function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const sec = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (sec < 60) return "только что";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} мин`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} ч`;
  return `${Math.round(hr / 24)} дн`;
}
