import { api } from "../../shared/api";
import type { Persona, Proxy } from "../../shared/types";

export interface PersonaBody {
  name: string;
  bio_template?: string | null;
  personality_tags?: string[];
  avatar_template_url?: string | null;
}

export interface ProxyBody {
  host: string;
  port: number;
  type: "socks5" | "http";
  geo?: string | null;
  login?: string | null;
}

export const personasApi = {
  list: () => api.get<Persona[]>("/personas"),
  create: (body: PersonaBody) => api.post<Persona>("/personas", body),
  update: (id: number, body: Partial<PersonaBody>) => api.patch<Persona>(`/personas/${id}`, body),
  remove: (id: number) => api.del<void>(`/personas/${id}`),
};

export interface ProxyOccupancy {
  id: number;
  host: string;
  port: number;
  type: "socks5" | "http";
  geo: string | null;
  status: "alive" | "dead" | "unchecked";
  last_checked_at: string | null;
  assigned_account_id: number | null;
  is_free: boolean;
}

export interface ProxyPick {
  proxy_id: number | null;
  detected_geo: string | null;
  reason: string | null;
}

export const proxiesApi = {
  list: () => api.get<Proxy[]>("/proxies"),
  pool: () => api.get<ProxyOccupancy[]>("/proxies/pool"),
  pick: (params: { phone?: string; geo?: string; strict_geo?: boolean }) => {
    const qs = new URLSearchParams();
    if (params.phone) qs.set("phone", params.phone);
    if (params.geo) qs.set("geo", params.geo);
    if (params.strict_geo === false) qs.set("strict_geo", "false");
    return api.get<ProxyPick>(`/proxies/pick?${qs.toString()}`);
  },
  create: (body: ProxyBody) => api.post<Proxy>("/proxies", body),
  remove: (id: number) => api.del<void>(`/proxies/${id}`),
  check: (id: number) => api.post<{ job_id?: string }>(`/proxies/${id}/check`),
  // Одна задача проверяет все прокси (backend: POST /proxies/check-all).
  checkAll: () => api.post<{ job_id?: string }>("/proxies/check-all"),
};
