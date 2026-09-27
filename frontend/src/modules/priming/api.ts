import { api } from "../../shared/api";
import type { PrimingCampaign, PrimingCampaignCreateBody } from "./types";

const BASE = "/modules/priming/campaigns";

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
};
