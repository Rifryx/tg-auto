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

/* Для любой работы (парсинг, кампании, прогрев-кампании, шиллинг) можно выбрать
 * аккаунт в ЛЮБОМ статусе — но «не идеальные» помечаем предупреждением, чтобы
 * пользователь понимал риск. «Идеальный» = в пуле (прогрет, свободен). */
export const IDEAL_WORK_STATUS: AccountStatus = "pool";

const WORK_WARNING: Partial<Record<AccountStatus, string>> = {
  created: "не залогинен / не прогрет",
  warming: "ещё на прогреве",
  assigned: "уже занят в работе",
  cooldown: "на паузе (риск/флуд)",
  banned: "забанен",
  retired: "выведен из работы",
};

/** Короткое предупреждение для «не идеального» аккаунта, или null если ок. */
export function accountWorkWarning(status: AccountStatus): string | null {
  return WORK_WARNING[status] ?? null;
}

/** Пороги готовности прогрева — зеркало worker/warming/presets.py.
 *  По факту завершение — по РАНЬШЕМУ из критериев (действия или дни),
 *  но у фронта нет счётчика действий, поэтому даём ETA по дням как
 *  верхнюю оценку: «не позже чем …». */
const WARMING_READY_DAYS = 14;

/** Если аккаунту уже столько суток или больше, прогрев короче: сами
 *  аккаунты telegram не считают его подозрительным, достаточно пары
 *  суток «обжитости» в системе. Пользователь жаловался: «аккаунтам 4
 *  месяца, не может им 2 недели нужно». Зеркально отражает
 *  WARMING_READY_DAYS_AGED в worker/warming/presets.py. */
const WARMING_AGED_THRESHOLD_DAYS = 60;
const WARMING_AGED_READY_DAYS = 3;

function warmingReadyDays(account: {
  created_at?: string | null;
  warming_started_at?: string | null;
}): number {
  const createdRaw = account.created_at;
  if (!createdRaw) return WARMING_READY_DAYS;
  const created = new Date(createdRaw).getTime();
  if (!Number.isFinite(created)) return WARMING_READY_DAYS;
  const ageDays = (Date.now() - created) / 86_400_000;
  return ageDays >= WARMING_AGED_THRESHOLD_DAYS
    ? WARMING_AGED_READY_DAYS
    : WARMING_READY_DAYS;
}

/** Человекочитаемая «подсказка» рядом со статусом аккаунта.
 *
 *  Пользователь жаловался: «риск бана 0 из 100, но он всё ещё на прогреве —
 *  непонятно когда закончится». Теперь по каждому не-pool статусу считаем
 *  ETA (на базе warming_started_at и cooldown_until) и даём человекочитаемую
 *  строку: «Прогрев: ещё ~3 дня», «Кулдаун: до 15:30», «В работе» и т.п.
 *
 *  Возвращает:
 *   - label — короткая подпись статуса (для «badge»);
 *   - detail — пояснение с ETA (для второй строки под именем);
 *   - warn — true если аккаунт «не идеален» для немедленной работы.
 */
export function accountStatusHint(a: {
  status: AccountStatus;
  warming_started_at?: string | null;
  cooldown_until?: string | null;
  created_at?: string | null;
}): {
  label: string;
  detail: string | null;
  shortDetail: string | null;
  warn: boolean;
} {
  const now = Date.now();
  switch (a.status) {
    case "pool":
      return { label: "Готов", detail: null, shortDetail: null, warn: false };
    case "assigned":
      return {
        label: "В работе",
        detail: "уже занят в кампании",
        shortDetail: "занят",
        warn: true,
      };
    case "warming": {
      if (!a.warming_started_at) {
        return {
          label: "Прогрев",
          detail: "идёт прогрев",
          shortDetail: "прогрев",
          warn: true,
        };
      }
      const started = new Date(a.warming_started_at).getTime();
      const totalDays = warmingReadyDays(a);
      const endsAt = started + totalDays * 86_400_000;
      const left = endsAt - now;
      if (left <= 0) {
        return {
          label: "Прогрев",
          detail: "вот-вот завершится",
          shortDetail: "скоро",
          warn: true,
        };
      }
      const long = formatDuration(left);
      return {
        label: "Прогрев",
        detail: `не позже чем через ${long}`,
        shortDetail: formatDurationCompact(left),
        warn: true,
      };
    }
    case "cooldown": {
      if (!a.cooldown_until) {
        return {
          label: "Пауза",
          detail: "кулдаун, риск/флуд",
          shortDetail: "пауза",
          warn: true,
        };
      }
      const until = new Date(a.cooldown_until).getTime();
      const left = until - now;
      if (left <= 0) {
        return {
          label: "Пауза",
          detail: "вот-вот снимется",
          shortDetail: "скоро",
          warn: true,
        };
      }
      return {
        label: "Пауза",
        detail: `освободится через ${formatDuration(left)}`,
        shortDetail: formatDurationCompact(left),
        warn: true,
      };
    }
    case "created":
      return {
        label: "Новый",
        detail: "не вошёл / не прогрет — требует запуска",
        shortDetail: "требует запуска",
        warn: true,
      };
    case "banned":
      return {
        label: "Забанен",
        detail: "работа невозможна",
        shortDetail: null,
        warn: true,
      };
    case "retired":
      return {
        label: "Выведен",
        detail: "выведен из работы",
        shortDetail: null,
        warn: true,
      };
    default:
      return { label: a.status, detail: null, shortDetail: null, warn: false };
  }
}

/** Форматирует миллисекунды в «3 дня», «5 часов», «40 минут». */
function formatDuration(ms: number): string {
  const minutes = Math.max(1, Math.floor(ms / 60_000));
  if (minutes >= 1440) {
    const days = Math.round(minutes / 1440);
    return `${days} ${days === 1 ? "день" : days < 5 ? "дня" : "дней"}`;
  }
  if (minutes >= 60) {
    const hours = Math.round(minutes / 60);
    return `${hours} ${hours === 1 ? "час" : hours < 5 ? "часа" : "часов"}`;
  }
  return `${minutes} ${minutes === 1 ? "минуту" : minutes < 5 ? "минуты" : "минут"}`;
}

/** Компактный «3 д», «5 ч», «40 м» — для бейджей/мини-карточек. */
function formatDurationCompact(ms: number): string {
  const minutes = Math.max(1, Math.floor(ms / 60_000));
  if (minutes >= 1440) return `${Math.round(minutes / 1440)} д`;
  if (minutes >= 60) return `${Math.round(minutes / 60)} ч`;
  return `${minutes} м`;
}

/** Сортировка: идеальные (pool) — вверх, затем прочие в порядке «полезности». */
const WORK_ORDER: Record<AccountStatus, number> = {
  pool: 0,
  assigned: 1,
  warming: 2,
  cooldown: 3,
  created: 4,
  retired: 5,
  banned: 6,
};

export function sortForWork<T extends { status: AccountStatus }>(items: T[]): T[] {
  return [...items].sort((a, b) => WORK_ORDER[a.status] - WORK_ORDER[b.status]);
}

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
