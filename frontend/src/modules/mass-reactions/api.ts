import { api } from "../../shared/api";
import type {
  ChatNotifyMode,
  MassReactionAccount,
  MassReactionCampaign,
  MassReactionCampaignCreateBody,
  MassReactionChat,
} from "./types";

const BASE = "/modules/mass-reactions/campaigns";

export const massReactionsApi = {
  list: () => api.get<MassReactionCampaign[]>(BASE),
  get: (id: number) => api.get<MassReactionCampaign>(`${BASE}/${id}`),
  create: (body: MassReactionCampaignCreateBody) =>
    api.post<MassReactionCampaign>(BASE, body),
  update: (id: number, body: Partial<MassReactionCampaignCreateBody>) =>
    api.patch<MassReactionCampaign>(`${BASE}/${id}`, body),
  remove: (id: number) => api.del<void>(`${BASE}/${id}`),

  start: (id: number) => api.post<MassReactionCampaign>(`${BASE}/${id}/start`, {}),
  pause: (id: number) => api.post<MassReactionCampaign>(`${BASE}/${id}/pause`, {}),
  stop: (id: number) => api.post<MassReactionCampaign>(`${BASE}/${id}/stop`, {}),

  listChats: (id: number) => api.get<MassReactionChat[]>(`${BASE}/${id}/chats`),
  addChats: (id: number, raw_text: string, notify_mode: ChatNotifyMode) =>
    api.post<MassReactionChat[]>(`${BASE}/${id}/chats`, { raw_text, notify_mode }),

  listAccounts: (id: number) =>
    api.get<MassReactionAccount[]>(`${BASE}/${id}/accounts`),
  addAccounts: (id: number, account_ids: number[]) =>
    api.post<MassReactionAccount[]>(`${BASE}/${id}/accounts`, { account_ids }),

  logsStats: (id: number) =>
    api.get<Record<string, number>>(`${BASE}/${id}/logs/stats`),
};
