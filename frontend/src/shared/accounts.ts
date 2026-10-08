import { api } from "./api";
import type {
  Account,
  AccountHealth,
  AccountRole,
  BulkJobDetail,
  BulkJobRead,
  CommentLog,
  ExportedSession,
  LoginStateResponse,
  MediaAsset,
  MonitoredChannel,
  Persona,
  ProfilePreview,
  ProjectChannel,
  Proxy,
  StatusHistoryRecord,
  WarmingActivity,
  WarmingProfile,
  WarmingScenario,
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
  importTData: (body: {
    phone: string;
    proxy_id: number;
    warming_profile: WarmingProfile;
    persona_id?: number | null;
    tdata_zip: File;
  }) => {
    const fd = new FormData();
    fd.append("phone", body.phone);
    fd.append("proxy_id", String(body.proxy_id));
    fd.append("warming_profile", body.warming_profile);
    if (body.persona_id != null) fd.append("persona_id", String(body.persona_id));
    fd.append("tdata_zip", body.tdata_zip);
    return api.postForm<Account>("/accounts/import-tdata", fd);
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
  health: (id: number) => api.get<AccountHealth>(`/accounts/${id}/health`),
  // Созданные аккаунтом каналы (project_channels).
  projectChannels: (id: number) =>
    api.get<ProjectChannel[]>(`/accounts/${id}/project-channels`),
  // Журнал комментариев аккаунта (что запостил + ошибки TG API).
  commentLogs: (id: number, limit = 50) =>
    api.get<CommentLog[]>(`/accounts/${id}/comment-logs?limit=${limit}`),
  // Экспорт StringSession выбранных аккаунтов (бэкап/перенос).
  exportSessions: (account_ids: number[]) =>
    api.post<ExportedSession[]>("/accounts/export-sessions", { account_ids }),
  // ИИ-превью профиля по персоне (без применения к Telegram).
  generateProfilePreview: (id: number, llm_provider = "deepseek") =>
    api.post<ProfilePreview>(`/accounts/${id}/profile/generate-preview`, { llm_provider }),
  // 2FA-пароль одного/нескольких аккаунтов (plaintext шифруется на сервере).
  set2fa: (body: {
    account_ids: number[];
    mode: "set_or_change" | "remove";
    password?: string;
    hint?: string;
    email?: string;
  }) => api.post<BulkJobRead>("/accounts/bulk/set-2fa", body),
  setProfile: (id: number, profile: WarmingProfile) =>
    api.patch<Account>(`/accounts/${id}/warming`, { profile }),
  // Конструктор сценариев прогрева (кастом поверх пресета, хранится в meta).
  warmingScenario: (id: number) =>
    api.get<WarmingScenario>(`/accounts/${id}/warming-scenario`),
  setWarmingScenario: (id: number, body: Partial<WarmingScenario>) =>
    api.put<WarmingScenario>(`/accounts/${id}/warming-scenario`, body),
  clearWarmingScenario: (id: number) =>
    api.del<void>(`/accounts/${id}/warming-scenario`),
  retire: (id: number) => api.post<Account>(`/accounts/${id}/actions/retire`),
  restore: (id: number) => api.post<Account>(`/accounts/${id}/actions/restore`),
  remove: (id: number) => api.del<void>(`/accounts/${id}`),
  // Pre-check номера на этапе ввода: занят ли уже (UI показывает подсказку до SMS).
  checkPhone: (phone: string) =>
    api.get<{ phone: string; normalized: string; exists: boolean }>(
      `/accounts/check-phone?phone=${encodeURIComponent(phone)}`,
    ),
  // Массовая проверка валидности/спамблока (ставит задачи в очередь).
  healthCheckBulk: (account_ids: number[], include_spam = false) =>
    api.post<{ enqueued: { account_id: number; job_id: string }[]; throttled: number[] }>(
      "/accounts/health/check-bulk",
      { account_ids, include_spam },
    ),
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

/* Медиа-ассеты (POST /media-assets) — источник для Stories. */
export const mediaApi = {
  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return api.postForm<MediaAsset>("/media-assets", fd);
  },
};

/* Bulk-задания (POST /bulk-jobs). Одиночное действие над аккаунтом —
   это job с account_ids=[id]; прогресс читаем через get(jobId). */
export const bulkApi = {
  create: (action_type: string, account_ids: number[], payload: Record<string, unknown> = {}) =>
    api.post<BulkJobRead>("/bulk-jobs", { action_type, account_ids, payload }),
  get: (jobId: number) => api.get<BulkJobDetail>(`/bulk-jobs/${jobId}`),
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
