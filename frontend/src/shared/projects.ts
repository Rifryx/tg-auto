/* API-клиент проектов и справочник ролей (этап 2, UI). */

import { api } from "./api";
import type { AccountRole, Project } from "./types";

export interface ProjectCreate {
  name: string;
  description?: string;
}

export interface ProjectUpdate {
  name?: string;
  description?: string | null;
}

export const projectsApi = {
  list: () => api.get<Project[]>("/projects"),
  create: (body: ProjectCreate) => api.post<Project>("/projects", body),
  update: (id: number, body: ProjectUpdate) =>
    api.patch<Project>(`/projects/${id}`, body),
  remove: (id: number) => api.del<void>(`/projects/${id}`),
};

export const ROLE_LABEL: Record<AccountRole, string> = {
  main: "Основной",
  support: "Поддержка",
  warmup: "Прогрев",
  burner: "Расходник",
};

export const ROLE_OPTIONS: { value: AccountRole; label: string }[] = [
  { value: "main", label: ROLE_LABEL.main },
  { value: "support", label: ROLE_LABEL.support },
  { value: "warmup", label: ROLE_LABEL.warmup },
  { value: "burner", label: ROLE_LABEL.burner },
];
