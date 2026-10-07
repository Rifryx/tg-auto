/* Клиентская проверка админ-роли.
 *
 * ВАЖНО: это только UX. Сервер — единственный источник правды. Он отдаст 404
 * на любой /admin/* для не-админа (см. api/deps/admin.py::require_admin).
 * Если кто-то подделает клиент — он всё равно ничего не получит с сервера.
 */
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "./api";

interface AdminMe {
  user_id: string;
  is_admin: true;
}

export function useIsAdmin(): { isAdmin: boolean; isChecking: boolean } {
  const q = useQuery({
    queryKey: ["admin", "me"],
    queryFn: async () => {
      try {
        return await api.get<AdminMe>("/admin/me");
      } catch (e) {
        if (e instanceof ApiError && (e.status === 404 || e.status === 401)) {
          return null;
        }
        throw e;
      }
    },
    // Кэшируем на всю сессию: реальная роль пользователя не меняется на ходу.
    staleTime: 5 * 60_000,
    retry: false,
  });
  return {
    isAdmin: q.data?.is_admin === true,
    isChecking: q.isPending,
  };
}

export interface AdminAnalytics {
  generated_at: string;
  users: {
    total: number;
    pro_active: number;
    free: number;
    new_7d: number;
    new_30d: number;
    expiring_7d: number;
    conversion_pct: number;
  };
  revenue: {
    by_currency: { provider: string; currency: string; count: number; total: number }[];
    paid_total: number;
    paid_30d: number;
    pending: number;
  };
  activity: {
    comments_24h: number;
    comments_7d: number;
    accounts_by_status: Record<string, number>;
    campaigns: { commenting: number; shilling: number; priming: number };
  };
  load: {
    bulk_jobs_queued: number;
    bulk_jobs_running: number;
    accounts_total: number;
    accounts_working: number;
    personas: number;
    proxies: number;
  };
}

export interface AdminPricing {
  price_usdt: number;
  price_stars: number;
  period_days: number;
  updated_at: string | null;
  effective: {
    price_usdt: number;
    price_stars: number;
    has_promo: boolean;
  };
}

export type PromoBadge = "gold" | "fire" | "neon";

export interface AdminPromotion {
  id: number;
  title: string;
  description: string | null;
  kind: "percent" | "fixed";
  percent_off: number | null;
  promo_price_usdt: number | null;
  promo_price_stars: number | null;
  badge_variant: PromoBadge;
  starts_at: string;
  ends_at: string;
  enabled: boolean;
}

export interface AdminPayment {
  id: number;
  user_id: string;
  provider: string;
  status: string;
  amount: number;
  currency: string;
  promo_id: number | null;
  created_at: string | null;
  paid_at: string | null;
}

export const adminApi = {
  stats: () =>
    api.get<{
      users: number;
      pro_users: number;
      accounts: number;
      personas: number;
      proxies: number;
      campaigns: number;
    }>("/admin/stats"),
  analytics: () => api.get<AdminAnalytics>("/admin/analytics"),
  listSubscriptions: () =>
    api.get<
      {
        user_id: string;
        plan_id: string;
        activated_at: string | null;
        expires_at: string | null;
        payment_method: string | null;
      }[]
    >("/admin/subscriptions"),
  setSubscription: (userId: string, plan_id: "free" | "pro", reason?: string) =>
    api.post<{ ok: boolean; user_id: string; plan_id: string }>(
      `/admin/subscriptions/${encodeURIComponent(userId)}`,
      { plan_id, reason },
    ),
  // --- цена ---
  getPricing: () => api.get<AdminPricing>("/admin/pricing"),
  setPricing: (body: { price_usdt: string; price_stars: number; period_days: number }) =>
    api.put<AdminPricing>("/admin/pricing", body),
  // --- акции ---
  listPromotions: () => api.get<AdminPromotion[]>("/admin/promotions"),
  createPromotion: (body: Record<string, unknown>) =>
    api.post<AdminPromotion>("/admin/promotions", body),
  patchPromotion: (id: number, body: Record<string, unknown>) =>
    api.patch<AdminPromotion>(`/admin/promotions/${id}`, body),
  deletePromotion: (id: number) =>
    api.del<{ ok: boolean }>(`/admin/promotions/${id}`),
  // --- платежи ---
  listPayments: (statusFilter?: string) =>
    api.get<AdminPayment[]>(
      `/admin/payments${statusFilter ? `?status_filter=${statusFilter}` : ""}`,
    ),
};
