/* Маленький аватар аккаунта: фото (avatar_url) либо инициал на плашке.
 * Единый компонент для списков/пикеров, где раньше рисовали только имя. */
export function AccountAvatar({
  avatarUrl,
  fallback,
  size = 28,
  colorful = false,
}: {
  avatarUrl?: string | null;
  fallback?: string | null;
  size?: number;
  /** Если true и avatar_url отсутствует — рисуем цветную плашку с инициалами
   *  (цвет стабильно выбирается по fallback). Используется в выборе коллектора
   *  в парсинге, чтобы аккаунты визуально отличались. */
  colorful?: boolean;
}) {
  const px = `${size}px`;
  if (avatarUrl) {
    return (
      <img
        src={avatarUrl}
        alt=""
        style={{ width: px, height: px }}
        className="shrink-0 rounded-full object-cover"
      />
    );
  }
  const text = (fallback ?? "?").trim();
  const initials = colorful
    ? text
        .split(/\s+/)
        .slice(0, 2)
        .map((p) => p.replace(/^[@+]/, "").charAt(0).toUpperCase())
        .join("") || "?"
    : text.slice(0, 1).toUpperCase();
  const style = colorful
    ? {
        width: px,
        height: px,
        background: AVATAR_PALETTE[Math.abs(hash(text)) % AVATAR_PALETTE.length],
      }
    : { width: px, height: px };
  const cls = colorful
    ? "flex shrink-0 items-center justify-center rounded-full text-[12px] font-semibold text-white"
    : "flex shrink-0 items-center justify-center rounded-full bg-surface-2 text-[12px] font-semibold text-text-secondary";
  return (
    <span style={style} className={cls}>
      {initials}
    </span>
  );
}

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return h;
}

const AVATAR_PALETTE = [
  "#5B8DEF",
  "#9B7EDE",
  "#E55A6A",
  "#F2994A",
  "#27AE60",
  "#2D9CDB",
  "#C06CF2",
  "#F2C94C",
  "#60C8A8",
  "#EB5757",
];
