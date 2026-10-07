/* API-клиент к серверному биллингу (см. api/routers/billing.py).
 *
 * Единый источник правды — сервер. Локальный UI-store используется как кэш
 * до/после запроса и как оптимистическое значение при успешной оплате.
 */
import { api, ApiError } from "./api";
import type { PlanId, PaymentMethodId } from "./plans";

export type PromoBadgeVariant = "gold" | "fire" | "neon";

export interface PromoInfo {
  id: number;
  title: string;
  description: string | null;
  badge_variant: PromoBadgeVariant;
  kind: "percent" | "fixed";
  ends_at: string;
}

export interface PricingInfo {
  price_usdt: number;
  price_stars: number;
  period_days: number;
  base_price_usdt: number;
  base_price_stars: number;
  has_promo: boolean;
  promo: PromoInfo | null;
}

export interface PlanSnapshot {
  plan_id: PlanId;
  limits: Record<string, number | boolean | string>;
  usage: Record<string, number>;
  expires_at: string | null;
  pricing: PricingInfo;
}

export interface InvoiceResponse {
  payment_id: number;
  provider: PaymentMethodId;
  url: string;
  amount: number;
  currency: string;
  status: string;
}

export interface PaymentCheck {
  status: "pending" | "paid" | "expired" | "failed";
  plan: PlanId;
}

/** Активная акция для шторки (per-user, с учётом скрытия). */
export interface CurtainPromo {
  id: number;
  title: string;
  description: string | null;
  badge_variant: PromoBadgeVariant;
  ends_at: string;
}

/** Тело 402-ответа от enforce_limit (api/deps/limits.py). */
export interface LimitExceededDetail {
  reason: "limit_exceeded";
  feature: string;
  used: number;
  limit: number;
  plan_id: PlanId;
}

/** Тело 402-ответа от require_feature (boolean-фича заблокирована планом). */
export interface FeatureLockedDetail {
  reason: "feature_locked";
  feature: string;
  plan_id: PlanId;
}

export const billingApi = {
  getPlan: () => api.get<PlanSnapshot>("/billing/plan"),
  setPlan: (plan_id: PlanId, payment_method?: PaymentMethodId) =>
    api.post<PlanSnapshot>("/billing/plan", { plan_id, payment_method }),
  createInvoice: (provider: PaymentMethodId) =>
    api.post<InvoiceResponse>("/billing/invoice", { plan_id: "pro", provider }),
  checkPayment: (paymentId: number) =>
    api.post<PaymentCheck>(`/billing/payments/${paymentId}/check`),
  getPromo: () => api.get<{ promo: CurtainPromo | null }>("/billing/promo"),
  dismissPromo: (promoId: number) =>
    api.post<{ ok: boolean }>(`/billing/promo/${promoId}/dismiss`),
};

/** Пытается извлечь структурный 402-детал из ошибки apiFetch. */
export function asLimitExceeded(e: unknown): LimitExceededDetail | null {
  if (!(e instanceof ApiError) || e.status !== 402) return null;
  const d = e.detail as LimitExceededDetail | null | undefined;
  if (d && typeof d === "object" && d.reason === "limit_exceeded") return d;
  return null;
}
