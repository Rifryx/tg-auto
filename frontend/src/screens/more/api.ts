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
  check: (id: number) => api.post<{ status?: string }>(`/proxies/${id}/check`),
  // Бэкенд не имеет /proxies/check-all — «проверить всё» ставит проверку по каждому.
  checkAll: async () => {
    const all = await proxiesApi.list();
    await Promise.all(all.map((p) => proxiesApi.check(p.id).catch(() => null)));
    return all.length;
  },
};
