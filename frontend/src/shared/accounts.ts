import { api } from "./api";
import type {
  Account,
  LoginStateResponse,
  MonitoredChannel,
  Persona,
  Proxy,
  StatusHistoryRecord,
  WarmingActivity,
  WarmingProfile,
} from "./types";

/* Типизированные вызовы accounts-эндпоинтов (api/routers/accounts.py и др.). */
export const accountsApi = {
  list: (status?: string) =>
    api.get<Account[]>(`/accounts${status && status !== "all" ? `?status=${status}` : ""}`),
  get: (id: number) => api.get<Account>(`/accounts/${id}`),
  patch: (
    id: number,
    body: Partial<{
      username: string | null;
      bio: string | null;
      avatar_url: string | null;
      persona_id: number | null;
      proxy_id: number | null;
    }>,
  ) => api.patch<Account>(`/accounts/${id}`, body),
  create: (body: {
    phone: string;
    proxy_id: number;
    persona_id?: number | null;
    warming_profile: WarmingProfile;
  }) => api.post<Account>("/accounts", body),
  history: (id: number) => api.get<StatusHistoryRecord[]>(`/accounts/${id}/history`),
  warming: (id: number) => api.get<WarmingActivity[]>(`/accounts/${id}/warming`),
  setProfile: (id: number, profile: WarmingProfile) =>
    api.patch<Account>(`/accounts/${id}/warming`, { profile }),
  retire: (id: number) => api.post<Account>(`/accounts/${id}/actions/retire`),
  loginState: (id: number) => api.get<LoginStateResponse>(`/accounts/${id}/login/state`),
  confirmCode: (id: number, code: string) =>
    api.post<LoginStateResponse>(`/accounts/${id}/login/confirm`, { code }),
  confirmPassword: (id: number, password: string) =>
    api.post<LoginStateResponse>(`/accounts/${id}/login/password`, { password }),
};

/* Каналы, которые мониторит аккаунт (modules/commenting/api/channels.py). */
export const channelsApi = {
  list: (accountId: number) =>
    api.get<MonitoredChannel[]>(`/accounts/${accountId}/channels`),
  add: (accountId: number, refs: string[], isFolder: boolean) =>
    api.post<MonitoredChannel[]>(`/accounts/${accountId}/channels`, {
      refs,
      is_folder: isFolder,
    }),
  remove: (accountId: number, channelId: number, unsubscribe = false) =>
    api.del<void>(
      `/accounts/${accountId}/channels/${channelId}?unsubscribe=${unsubscribe}`,
    ),
};

export const catalogApi = {
  proxies: () => api.get<Proxy[]>("/proxies"),
  proxy: (id: number) => api.get<Proxy>(`/proxies/${id}`),
  personas: () => api.get<Persona[]>("/personas"),
};

/** Отвязать аккаунт от кампании commenting (когда assigned). */
export function detachFromCampaign(campaignId: number, accountId: number) {
  return api.del<void>(`/modules/commenting/campaigns/${campaignId}/accounts/${accountId}`);
}
