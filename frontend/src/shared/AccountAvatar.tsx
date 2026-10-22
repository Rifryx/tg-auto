/* Маленький аватар аккаунта: фото (avatar_url) либо инициал на плашке.
 * Единый компонент для списков/пикеров, где раньше рисовали только имя. */
export function AccountAvatar({
  avatarUrl,
  fallback,
  size = 28,
}: {
  avatarUrl?: string | null;
  fallback?: string | null;
  size?: number;
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
  return (
    <span
      style={{ width: px, height: px }}
      className="flex shrink-0 items-center justify-center rounded-full bg-surface-2 text-[12px] font-semibold text-text-secondary"
    >
      {(fallback ?? "?").slice(0, 1).toUpperCase()}
    </span>
  );
}
