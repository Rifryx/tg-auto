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
};
