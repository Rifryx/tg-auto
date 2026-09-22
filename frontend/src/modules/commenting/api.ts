import { api } from "../../shared/api";
import type {
  AccountPreset,
  AccountPresetCreateBody,
  AccountPresetUpdateBody,
  AiProtectionStatus,
  Campaign,
  CampaignAccount,
  CampaignAccountPatchBody,
  CampaignChannel,
  CampaignCreateBody,
  CampaignUpdateBody,
  ChannelBlacklistEntry,
  CommentLog,
  DelayPreset,
  DelayPresetCreateBody,
  DelayPresetUpdateBody,
} from "./types";

const BASE = "/modules/commenting/campaigns";
const PRESETS = "/modules/commenting/presets";

/* Типизированные вызовы commenting-эндпоинтов (modules/commenting/api/router.py). */
export const commentingApi = {
  list: () => api.get<Campaign[]>(BASE),
  get: (id: number) => api.get<Campaign>(`${BASE}/${id}`),
  create: (body: CampaignCreateBody) => api.post<Campaign>(BASE, body),
  update: (id: number, body: CampaignUpdateBody) =>
    api.patch<Campaign>(`${BASE}/${id}`, body),
  remove: (id: number) => api.del<void>(`${BASE}/${id}`),
  accounts: (id: number) => api.get<CampaignAccount[]>(`${BASE}/${id}/accounts`),
  attach: (
    id: number,
    accountId: number,
    extra?: { probability_override?: number | null; override_prompt?: string | null },
  ) =>
    api.post<CampaignAccount>(`${BASE}/${id}/accounts`, {
      account_id: accountId,
      ...extra,
    }),
  patchAccount: (id: number, accountId: number, body: CampaignAccountPatchBody) =>
    api.patch<CampaignAccount>(`${BASE}/${id}/accounts/${accountId}`, body),
  detach: (id: number, accountId: number) =>
    api.del<void>(`${BASE}/${id}/accounts/${accountId}`),
  logs: (id: number, limit = 50) =>
    api.get<CommentLog[]>(`${BASE}/${id}/logs?limit=${limit}`),

  channels: (id: number) =>
    api.get<CampaignChannel[]>(`${BASE}/${id}/channels`),
  addChannels: (id: number, raw_inputs: string[]) =>
    api.post<CampaignChannel[]>(`${BASE}/${id}/channels`, { raw_inputs }),
  removeChannel: (id: number, channelId: number) =>
    api.del<void>(`${BASE}/${id}/channels/${channelId}`),

  blacklist: (id: number) =>
    api.get<ChannelBlacklistEntry[]>(`${BASE}/${id}/blacklist`),
  addBlacklist: (
    id: number,
    body: { chat_id?: number | null; username?: string | null; reason?: string | null },
  ) => api.post<ChannelBlacklistEntry>(`${BASE}/${id}/blacklist`, body),
  removeBlacklist: (id: number, entryId: number) =>
    api.del<void>(`${BASE}/${id}/blacklist/${entryId}`),
};

/* Пресеты аккаунтов и задержек (§ Этап 1). Delay-list возвращает системные
   пресеты (Мин/Рекоменд/Макс) + пользовательские; редактировать/удалять
   системные нельзя — backend вернёт 404. */
export const accountPresetsApi = {
  list: () => api.get<AccountPreset[]>(`${PRESETS}/accounts`),
  create: (body: AccountPresetCreateBody) =>
    api.post<AccountPreset>(`${PRESETS}/accounts`, body),
  update: (id: number, body: AccountPresetUpdateBody) =>
    api.patch<AccountPreset>(`${PRESETS}/accounts/${id}`, body),
  remove: (id: number) => api.del<void>(`${PRESETS}/accounts/${id}`),
};

export const aiProtectionApi = {
  status: () =>
    api.get<AiProtectionStatus>("/modules/commenting/ai-protection/status"),
};

export const delayPresetsApi = {
  list: () => api.get<DelayPreset[]>(`${PRESETS}/delays`),
  create: (body: DelayPresetCreateBody) =>
    api.post<DelayPreset>(`${PRESETS}/delays`, body),
  update: (id: number, body: DelayPresetUpdateBody) =>
    api.patch<DelayPreset>(`${PRESETS}/delays/${id}`, body),
  remove: (id: number) => api.del<void>(`${PRESETS}/delays/${id}`),
};
