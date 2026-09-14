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

export const proxiesApi = {
  list: () => api.get<Proxy[]>("/proxies"),
  create: (body: ProxyBody) => api.post<Proxy>("/proxies", body),
  remove: (id: number) => api.del<void>(`/proxies/${id}`),
  check: (id: number) => api.post<{ job_id?: string }>(`/proxies/${id}/check`),
  // Одна задача проверяет все прокси (backend: POST /proxies/check-all).
  checkAll: () => api.post<{ job_id?: string }>("/proxies/check-all"),
};
