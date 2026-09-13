import { api } from "../../shared/api";
import type {
  Campaign,
  CampaignAccount,
  CampaignCreateBody,
  CampaignUpdateBody,
  CommentLog,
} from "./types";

const BASE = "/modules/commenting/campaigns";

/* Типизированные вызовы commenting-эндпоинтов (modules/commenting/api/router.py). */
export const commentingApi = {
  list: () => api.get<Campaign[]>(BASE),
  get: (id: number) => api.get<Campaign>(`${BASE}/${id}`),
  create: (body: CampaignCreateBody) => api.post<Campaign>(BASE, body),
  update: (id: number, body: CampaignUpdateBody) =>
    api.patch<Campaign>(`${BASE}/${id}`, body),
  remove: (id: number) => api.del<void>(`${BASE}/${id}`),
  accounts: (id: number) => api.get<CampaignAccount[]>(`${BASE}/${id}/accounts`),
  attach: (id: number, accountId: number) =>
    api.post<CampaignAccount>(`${BASE}/${id}/accounts`, { account_id: accountId }),
  detach: (id: number, accountId: number) =>
    api.del<void>(`${BASE}/${id}/accounts/${accountId}`),
  logs: (id: number, limit = 50) =>
    api.get<CommentLog[]>(`${BASE}/${id}/logs?limit=${limit}`),
};
