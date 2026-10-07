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

/** Роли аккаунта (воркер/техничка/прогрев/бёрнер) — §6.1 архитектуры. */
export const ROLE_LABEL: Record<string, string> = {
  main: "Основной",
  support: "Поддержка",
  warmup: "Прогрев",
  burner: "Бёрнер",
};

/** Контейнер-задача (к чему привязан аккаунт) → читаемое имя. */
export const CONTAINER_LABEL: Record<string, string> = {
  commenting: "Нейрокомментинг",
  shilling: "НейроШиллинг",
  priming: "Прайминг",
  parsing: "Парсинг",
};

export const PROFILE_LABEL: Record<WarmingProfile, string> = {
  minimal: "Мин.",
  medium: "Средний",
  dense: "Плотный",
};

/** Типы действий прогрева → читаемые метки (для конструктора сценариев). */
export const WARMING_ACTION_LABEL: Record<string, string> = {
  read_history: "Читать историю",
  view_media: "Смотреть медиа",
  reaction: "Ставить реакции",
  idle_online: "Быть онлайн",
  subscribe_channel: "Подписки на каналы",
  join_group: "Вступать в группы",
  interact_with_peer: "Общение с аккаунтами",
  update_profile: "Обновлять профиль",
};

/** Пороги пресетов прогрева (зеркало worker/warming/presets.py) — для
    предзаполнения конструктора сценариев. */
export const PRESET_WARMING_DEFAULTS: Record<
  WarmingProfile,
  { interval: [number, number]; actions: [number, number] }
> = {
  minimal: { interval: [48, 72], actions: [1, 2] },
  medium: { interval: [20, 28], actions: [2, 5] },
  dense: { interval: [6, 10], actions: [5, 10] },
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
