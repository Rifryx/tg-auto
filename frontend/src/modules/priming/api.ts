import { api } from "../../shared/api";
import type {
  PrimingCampaign,
  PrimingCampaignCreateBody,
  PrimingExecutionOutcome,
  PrimingLiveSnapshot,
  PrimingLogsPage,
} from "./types";

const BASE = "/modules/priming/campaigns";

export interface AttachAccountsResult {
  attached: number[];
  skipped_busy: number[];
  skipped_duplicate: number[];
}

export interface TargetImportResult {
  inserted: number;
  skipped_duplicate: number;
  skipped_blacklisted: number;
  skipped_invalid: number;
}

export interface TargetItem {
  tg_user_id?: number | null;
  username?: string | null;
  phone?: string | null;
}

/* Типизированные вызовы priming-эндпоинтов
   (см. modules/priming/api/router.py). */
export const primingApi = {
  list: () => api.get<PrimingCampaign[]>(BASE),
  get: (id: number) => api.get<PrimingCampaign>(`${BASE}/${id}`),
  create: (body: PrimingCampaignCreateBody) =>
    api.post<PrimingCampaign>(BASE, body),
  remove: (id: number) => api.del<void>(`${BASE}/${id}`),

  start: (id: number) => api.post<PrimingCampaign>(`${BASE}/${id}/start`, {}),
  pause: (id: number) => api.post<PrimingCampaign>(`${BASE}/${id}/pause`, {}),
  resume: (id: number) => api.post<PrimingCampaign>(`${BASE}/${id}/resume`, {}),
  stop: (id: number) => api.post<PrimingCampaign>(`${BASE}/${id}/stop`, {}),

  update: (id: number, body: Partial<PrimingCampaignCreateBody> & { dry_run?: boolean }) =>
    api.patch<PrimingCampaign>(`${BASE}/${id}`, body),
  live: (id: number) => api.get<PrimingLiveSnapshot>(`${BASE}/${id}/live`),

  logs: (
    id: number,
    params: {
      outcome?: PrimingExecutionOutcome;
      q?: string;
      cursor?: number;
      limit?: number;
    } = {},
  ) => {
    const qs = new URLSearchParams();
    if (params.outcome) qs.set("outcome", params.outcome);
    if (params.q) qs.set("q", params.q);
    if (params.cursor != null) qs.set("cursor", String(params.cursor));
    if (params.limit != null) qs.set("limit", String(params.limit));
    const tail = qs.toString();
    return api.get<PrimingLogsPage>(
      `${BASE}/${id}/logs${tail ? `?${tail}` : ""}`,
    );
  },
  exportLogsCsvUrl: (
    id: number,
    params: { outcome?: PrimingExecutionOutcome; q?: string } = {},
  ) => {
    const qs = new URLSearchParams();
    if (params.outcome) qs.set("outcome", params.outcome);
    if (params.q) qs.set("q", params.q);
    const tail = qs.toString();
    return `${BASE}/${id}/logs/export.csv${tail ? `?${tail}` : ""}`;
  },

  attachAccounts: (id: number, accountIds: number[]) =>
    api.post<AttachAccountsResult>(`${BASE}/${id}/accounts`, {
      account_ids: accountIds,
    }),
  importTargets: (id: number, targets: TargetItem[]) =>
    api.post<TargetImportResult>(`${BASE}/${id}/targets/import`, { targets }),
  importFromList: (id: number, parsedListId: number) =>
    api.post<TargetImportResult>(`${BASE}/${id}/targets/import-list`, {
      parsed_list_id: parsedListId,
    }),
};
