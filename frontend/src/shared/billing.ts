/* API-клиент к серверному биллингу (см. api/routers/billing.py).
 *
 * Единый источник правды — сервер. Локальный UI-store используется как кэш
 * до/после запроса и как оптимистическое значение при успешной оплате.
 */
import { api, ApiError } from "./api";
import type { PlanId, PaymentMethodId } from "./plans";

export interface PlanSnapshot {
  plan_id: PlanId;
  limits: Record<string, number | boolean | string>;
  usage: Record<string, number>;
}

/** Тело 402-ответа от enforce_limit (api/deps/limits.py). */
export interface LimitExceededDetail {
  reason: "limit_exceeded";
  feature: string;
  used: number;
  limit: number;
  plan_id: PlanId;
}

export const billingApi = {
  getPlan: () => api.get<PlanSnapshot>("/billing/plan"),
  setPlan: (plan_id: PlanId, payment_method?: PaymentMethodId) =>
    api.post<PlanSnapshot>("/billing/plan", { plan_id, payment_method }),
};

/** Пытается извлечь структурный 402-детал из ошибки apiFetch. */
export function asLimitExceeded(e: unknown): LimitExceededDetail | null {
  if (!(e instanceof ApiError) || e.status !== 402) return null;
  const d = e.detail as LimitExceededDetail | null | undefined;
  if (d && typeof d === "object" && d.reason === "limit_exceeded") return d;
  return null;
}
