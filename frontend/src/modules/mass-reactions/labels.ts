import type {
  ChatState,
  HumanizerMode,
  MassReactionStatus,
  WarmupProfile,
} from "./types";

export const STATUS_LABEL: Record<MassReactionStatus, string> = {
  draft: "Черновик",
  queued: "В очереди",
  running: "Идёт",
  paused: "Пауза",
  stopped: "Остановлена",
  finished: "Завершена",
  failed: "Ошибка",
};

export const STATUS_TONE: Record<MassReactionStatus, string> = {
  draft: "bg-status-neutral",
  queued: "bg-status-warning",
  running: "bg-status-active",
  paused: "bg-status-warning",
  stopped: "bg-status-neutral",
  finished: "bg-status-active",
  failed: "bg-status-critical",
};

export const WARMUP_LABEL: Record<WarmupProfile, string> = {
  cold: "Cold · медленно",
  warm: "Warm · средне",
  hot: "Hot · быстро",
};

export const HUMANIZER_LABEL: Record<HumanizerMode, string> = {
  off: "Выкл · только реакции",
  balanced: "Сбалансированный",
  aggressive: "Агрессивный",
};

export const CHAT_STATE_LABEL: Record<ChatState, string> = {
  pending: "Ожидает",
  active: "В работе",
  not_subscribed: "Не в подписках",
  joining: "Вступаем",
  failed: "Ошибка",
  disabled: "Выключен",
};

// Белый список реакций (частые TG-эмодзи). Мульти-выбор при создании.
export const REACTION_EMOJIS = [
  "👍", "❤️", "🔥", "🥰", "👏", "😁", "🎉", "🤩", "🙏", "👌", "💯", "⚡",
];
