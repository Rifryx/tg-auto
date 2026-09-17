/* Тарифы и лимиты — единая точка правды для фронта.
 *
 * Пока планов два: Free и Pro. Внутри лежат структурные лимиты и флаги фич;
 * при добавлении нового модуля добавляем ключ в FeatureKey и значения в оба
 * плана — UI биллинга подхватит сам.
 */

export type PlanId = "free" | "pro";

export type PaymentMethodId = "stars" | "crypto";

export type FeatureKey =
  // База
  | "accounts_max"
  | "personas_max"
  | "proxies_max"
  // Модуль commenting
  | "campaigns_active_max"
  | "comments_per_day"
  | "channels_watch_max"
  // Общее
  | "ai_provider_custom"
  | "priority_queue"
  | "audit_history_days"
  | "support_level";

export type FeatureValue = number | boolean | "community" | "priority";

export interface Plan {
  id: PlanId;
  name: string;
  priceMonth: number;                // в USD; 0 = free
  priceStars?: number;               // цена в Telegram Stars
  tagline: string;
  bullets: string[];                 // ключевые тезисы карточки
  limits: Record<FeatureKey, FeatureValue>;
}

export const UNLIMITED = -1;

export const PLANS: Plan[] = [
  {
    id: "free",
    name: "Free",
    priceMonth: 0,
    tagline: "Попробовать без оплаты",
    bullets: [
      "1 аккаунт, 1 персона",
      "1 активная кампания",
      "До 20 комментариев в сутки",
      "История активности — 3 дня",
      "Комьюнити-поддержка",
    ],
    limits: {
      accounts_max: 1,
      personas_max: 1,
      proxies_max: 1,
      campaigns_active_max: 1,
      comments_per_day: 20,
      channels_watch_max: 3,
      ai_provider_custom: false,
      priority_queue: false,
      audit_history_days: 3,
      support_level: "community",
    },
  },
  {
    id: "pro",
    name: "Pro",
    priceMonth: 19,
    priceStars: 950,
    tagline: "Весь функционал без ограничений",
    bullets: [
      "Безлимит аккаунтов, персон и прокси",
      "Безлимит активных кампаний",
      "До 3000 комментариев в сутки",
      "Свой ключ модели, приоритет в очереди",
      "История активности — 365 дней",
      "Приоритетная поддержка",
    ],
    limits: {
      accounts_max: UNLIMITED,
      personas_max: UNLIMITED,
      proxies_max: UNLIMITED,
      campaigns_active_max: UNLIMITED,
      comments_per_day: 3000,
      channels_watch_max: UNLIMITED,
      ai_provider_custom: true,
      priority_queue: true,
      audit_history_days: 365,
      support_level: "priority",
    },
  },
];

export const PAYMENT_METHODS: {
  id: PaymentMethodId;
  name: string;
  hint: string;
}[] = [
  { id: "stars", name: "Telegram Stars", hint: "Оплата внутри Telegram" },
  { id: "crypto", name: "Crypto Bot", hint: "USDT/TON/BTC через @CryptoBot" },
];

export function getPlan(id: PlanId): Plan {
  return PLANS.find((p) => p.id === id) ?? PLANS[0];
}

export function formatLimit(v: FeatureValue): string {
  if (v === UNLIMITED) return "∞";
  if (typeof v === "boolean") return v ? "есть" : "—";
  if (typeof v === "number") return v.toLocaleString("ru-RU");
  return v === "priority" ? "приоритет" : "community";
}
