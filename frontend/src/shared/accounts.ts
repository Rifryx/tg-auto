import { api } from "./api";
import type {
  Account,
  AccountRole,
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
      first_name: string | null;
      last_name: string | null;
      username: string | null;
      bio: string | null;
      avatar_url: string | null;
      persona_id: number | null;
      proxy_id: number | null;
      project_id: number | null;
      role: AccountRole | null;
      tags: string[];
    }>,
  ) => api.patch<Account>(`/accounts/${id}`, body),
  create: (body: {
    phone: string;
    proxy_id: number;
    persona_id?: number | null;
    warming_profile: WarmingProfile;
  }) => api.post<Account>("/accounts", body),
  importSession: (body: {
    phone: string;
    proxy_id: number;
    warming_profile: WarmingProfile;
    session_string?: string;
    session_file?: File;
  }) => {
    const fd = new FormData();
    fd.append("phone", body.phone);
    fd.append("proxy_id", String(body.proxy_id));
    fd.append("warming_profile", body.warming_profile);
    if (body.session_string) fd.append("session_string", body.session_string);
    if (body.session_file) fd.append("session_file", body.session_file);
    return api.postForm<Account>("/accounts/import-session", fd);
  },
  bulkImport: (archive: File, mapping: File) => {
    const fd = new FormData();
    fd.append("archive", archive);
    fd.append("mapping", mapping);
    return api.postForm<{
      imported: { phone: string; account_id: number }[];
      skipped: { phone: string; reason: string }[];
      totals: { imported: number; skipped: number };
    }>("/accounts/bulk-import", fd);
  },
  history: (id: number) => api.get<StatusHistoryRecord[]>(`/accounts/${id}/history`),
  warming: (id: number) => api.get<WarmingActivity[]>(`/accounts/${id}/warming`),
  setProfile: (id: number, profile: WarmingProfile) =>
    api.patch<Account>(`/accounts/${id}/warming`, { profile }),
  retire: (id: number) => api.post<Account>(`/accounts/${id}/actions/retire`),
  restore: (id: number) => api.post<Account>(`/accounts/${id}/actions/restore`),
  remove: (id: number) => api.del<void>(`/accounts/${id}`),
  loginState: (id: number) => api.get<LoginStateResponse>(`/accounts/${id}/login/state`),
  confirmCode: (id: number, code: string) =>
    api.post<LoginStateResponse>(`/accounts/${id}/login/confirm`, { code }),
  confirmPassword: (id: number, password: string) =>
    api.post<LoginStateResponse>(`/accounts/${id}/login/password`, { password }),
  // Recovery-email для 2FA (этап 7, backlog #1).
  recoveryEmailState: (id: number) =>
    api.get<{
      email: string | null;
      pending_email: string | null;
      code_length: number | null;
      confirmed_at: string | null;
    }>(`/accounts/${id}/2fa/recovery-email/state`),
  requestRecoveryEmail: (id: number, email: string, password: string) =>
    api.post<{ queued: boolean }>(`/accounts/${id}/2fa/recovery-email/request`, {
      email,
      password,
    }),
  confirmRecoveryEmail: (id: number, code: string) =>
    api.post<{ queued: boolean }>(`/accounts/${id}/2fa/recovery-email/confirm`, {
      code,
    }),
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
  createProxy: (body: {
    host: string;
    port: number;
    type: "socks5" | "http";
    login?: string | null;
    password?: string | null;
    geo?: string | null;
  }) => api.post<Proxy>("/proxies", body),
  personas: () => api.get<Persona[]>("/personas"),
};

/** Отвязать аккаунт от кампании commenting (когда assigned). */
export function detachFromCampaign(campaignId: number, accountId: number) {
  return api.del<void>(`/modules/commenting/campaigns/${campaignId}/accounts/${accountId}`);
}
