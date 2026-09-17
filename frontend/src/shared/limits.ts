/* Гейт по лимитам тарифа.
 *
 * Задача — реально ограничить пользование на фронте, не размазывая логику
 * по экранам. Точка правды одна: план из useCurrentPlan() → числовой лимит.
 * Использование считаем из уже закэшированных react-query данных, чтобы не
 * гонять отдельные запросы «сколько у меня всего».
 *
 * Правила замены: изменил цифры в plans.ts — весь UI подхватил без правок.
 * Появился новый ресурс — добавил ключ в FeatureKey в plans.ts, добавил
 * функцию используемого счётчика в USAGE_HOOKS и всё.
 */

import { useQueryClient } from "@tanstack/react-query";
import type { FeatureKey } from "./plans";
import { UNLIMITED } from "./plans";
import { useCurrentPlan } from "./store";

export interface LimitStatus {
  used: number;
  limit: number;          // −1 = безлимит
  remaining: number;      // Infinity если безлимит
  atLimit: boolean;
  planId: string;
}

/* Сколько ресурсов уже создано.
 * Читаем из react-query кэша — если пользователь ещё не открывал соотв.
 * экран, кэша нет, считаем 0. Это осознанный компромисс: если бэкенд
 * реально даёт больше, чем показывает фронт, гейт всё равно сработает
 * при попытке создать N+1 (бэкенд-валидация — отдельный шаг). */
type CountReader = (qc: ReturnType<typeof useQueryClient>) => number;

const COUNT_READERS: Partial<Record<FeatureKey, CountReader>> = {
  accounts_max: (qc) => {
    // Кэш кампаний-независимого списка аккаунтов лежит по ["accounts", filter],
    // но правильнее было бы отдельный ключ ["accounts", "all"]. Пока считаем
    // максимум по всем закэшированным фильтрам — этого достаточно для гейта.
    let max = 0;
    for (const [key, data] of qc.getQueryCache().findAll({ queryKey: ["accounts"] }).map(
      (q) => [q.queryKey, q.state.data] as const,
    )) {
      void key;
      if (Array.isArray(data)) max = Math.max(max, data.length);
    }
    return max;
  },
  personas_max: (qc) => {
    const data = qc.getQueryData<unknown[]>(["personas"]);
    return Array.isArray(data) ? data.length : 0;
  },
  proxies_max: (qc) => {
    const data = qc.getQueryData<unknown[]>(["proxies"]);
    return Array.isArray(data) ? data.length : 0;
  },
  campaigns_active_max: (qc) => {
    const data = qc.getQueryData<{ status?: string }[]>(["campaigns"]);
    if (!Array.isArray(data)) return 0;
    // Считаем «занятыми» активные и на паузе — они держат слот.
    return data.filter((c) => c.status !== "archived" && c.status !== "finished").length;
  },
};

const NUMERIC_KEYS: FeatureKey[] = [
  "accounts_max",
  "personas_max",
  "proxies_max",
  "campaigns_active_max",
  "comments_per_day",
  "channels_watch_max",
  "audit_history_days",
];

function isNumericKey(k: FeatureKey): boolean {
  return NUMERIC_KEYS.includes(k);
}

/** Статус конкретного лимита. Возвращает undefined для не-числовых ключей. */
export function useLimit(feature: FeatureKey): LimitStatus | undefined {
  const plan = useCurrentPlan();
  const qc = useQueryClient();
  if (!isNumericKey(feature)) return undefined;

  const rawLimit = plan.limits[feature];
  const limit = typeof rawLimit === "number" ? rawLimit : 0;

  const reader = COUNT_READERS[feature];
  const used = reader ? reader(qc) : 0;

  const remaining = limit === UNLIMITED ? Number.POSITIVE_INFINITY : Math.max(0, limit - used);
  const atLimit = limit !== UNLIMITED && used >= limit;

  return { used, limit, remaining, atLimit, planId: plan.id };
}

/** Значение флаг-фичи (boolean-лимиты вроде «свой ключ модели»). */
export function useFeatureEnabled(feature: FeatureKey): boolean {
  const plan = useCurrentPlan();
  const v = plan.limits[feature];
  if (typeof v === "boolean") return v;
  if (v === UNLIMITED) return true;
  if (typeof v === "number") return v > 0;
  return false;
}

/* Человекочитаемые названия ресурсов — для лимит-баннеров. */
export const LIMIT_LABEL: Partial<Record<FeatureKey, string>> = {
  accounts_max: "аккаунтов",
  personas_max: "персон",
  proxies_max: "прокси",
  campaigns_active_max: "активных кампаний",
  comments_per_day: "комментариев в сутки",
  channels_watch_max: "каналов",
};
