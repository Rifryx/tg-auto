import type { AccountStatus, WarmingProfile } from "./types";

/* Маппинг стадий → цвет статуса (UI-DESIGN-BRIEF.md §7).
   Значения — tailwind-классы на токены (не hex): единый источник — tokens.css.
   dotClass — цвет 8px точки; badge — «мягкая» капсула (фон = цвет на ~15%,
   текст = цвет полной насыщенности) через util-классы в index.css. */
type StatusTone = "active" | "warning" | "critical" | "neutral";

const STATUS_TONE: Record<AccountStatus, StatusTone> = {
  pool: "active",
  assigned: "active",
  warming: "warning",
  cooldown: "warning",
  banned: "critical",
  created: "neutral",
  retired: "neutral",
};

const TONE_DOT: Record<StatusTone, string> = {
  active: "bg-status-active",
  warning: "bg-status-warning",
  critical: "bg-status-critical",
  neutral: "bg-status-neutral",
};

// Мягкий бейдж (§7): фон = статусный цвет на ~16% (color-mix по токену,
// не hex), текст = цвет полной насыщенности. Строки статичны → tailwind их
// генерирует; браузеры без color-mix деградируют до прозрачного фона.
const TONE_BADGE: Record<StatusTone, string> = {
  active:
    "text-status-active bg-[color-mix(in_srgb,var(--status-active)_16%,transparent)]",
  warning:
    "text-status-warning bg-[color-mix(in_srgb,var(--status-warning)_16%,transparent)]",
  critical:
    "text-status-critical bg-[color-mix(in_srgb,var(--status-critical)_16%,transparent)]",
  neutral:
    "text-status-neutral bg-[color-mix(in_srgb,var(--status-neutral)_16%,transparent)]",
};

export const STATUS_LABEL: Record<AccountStatus, string> = {
  created: "Создан",
  warming: "Прогрев",
  pool: "В пуле",
  assigned: "В работе",
  cooldown: "Пауза",
  retired: "Выведен",
  banned: "Бан",
};

export function statusTone(status: AccountStatus): StatusTone {
  return STATUS_TONE[status];
}

export function statusDotClass(status: AccountStatus): string {
  return TONE_DOT[STATUS_TONE[status]];
}

export function statusBadgeClass(status: AccountStatus): string {
  return TONE_BADGE[STATUS_TONE[status]];
}

export const PROFILE_LABEL: Record<WarmingProfile, string> = {
  minimal: "Мин.",
  medium: "Средний",
  dense: "Плотный",
};

/** Фильтры списка аккаунтов (§ требований промпта 26). */
export const ACCOUNT_FILTERS: { value: AccountStatus | "all"; label: string }[] = [
  { value: "all", label: "Все" },
  { value: "pool", label: "В пуле" },
  { value: "assigned", label: "В работе" },
  { value: "warming", label: "Прогрев" },
  { value: "cooldown", label: "Пауза" },
  { value: "banned", label: "Бан" },
];
