import { api } from "../../shared/api";
import type {
  AttachAccountBody,
  BlacklistCreateBody,
  BlacklistEntry,
  Campaign,
  CampaignAccount,
  CampaignAccountPatchBody,
  CampaignCreateBody,
  CampaignReadiness,
  CampaignStats,
  CampaignUpdateBody,
  ExecutionLog,
  GeneratedScenario,
  Role,
  RoleCreateBody,
  RoleUpdateBody,
  Scenario,
  ScenarioCreateBody,
  ScenarioGenerateBody,
  Step,
  StepCreateBody,
  StepUpdateBody,
  Target,
} from "./types";

const BASE = "/modules/shilling/campaigns";
const SCEN = "/modules/shilling/scenarios";

/* Типизированные вызовы shilling-эндпоинтов (modules/shilling/api/router.py). */
export const shillingApi = {
  // Кампании
  list: () => api.get<Campaign[]>(BASE),
  get: (id: number) => api.get<Campaign>(`${BASE}/${id}`),
  create: (body: CampaignCreateBody) => api.post<Campaign>(BASE, body),
  update: (id: number, body: CampaignUpdateBody) =>
    api.patch<Campaign>(`${BASE}/${id}`, body),
  remove: (id: number) => api.del<void>(`${BASE}/${id}`),

  // Сценарий кампании
  scenario: (id: number) => api.get<Scenario>(`${BASE}/${id}/scenario`),
  putScenario: (id: number, body: ScenarioCreateBody) =>
    api.put<Scenario>(`${BASE}/${id}/scenario`, body),
  generateScenario: (id: number, body: ScenarioGenerateBody) =>
    api.post<GeneratedScenario>(`${BASE}/${id}/scenario/generate`, body),

  // Роли сценария
  roles: (scenarioId: number) => api.get<Role[]>(`${SCEN}/${scenarioId}/roles`),
  addRole: (scenarioId: number, body: RoleCreateBody) =>
    api.post<Role>(`${SCEN}/${scenarioId}/roles`, body),
  updateRole: (scenarioId: number, roleId: number, body: RoleUpdateBody) =>
    api.patch<Role>(`${SCEN}/${scenarioId}/roles/${roleId}`, body),
  removeRole: (scenarioId: number, roleId: number) =>
    api.del<void>(`${SCEN}/${scenarioId}/roles/${roleId}`),

  // Шаги сценария
  steps: (scenarioId: number) => api.get<Step[]>(`${SCEN}/${scenarioId}/steps`),
  addStep: (scenarioId: number, body: StepCreateBody) =>
    api.post<Step>(`${SCEN}/${scenarioId}/steps`, body),
  updateStep: (scenarioId: number, stepId: number, body: StepUpdateBody) =>
    api.patch<Step>(`${SCEN}/${scenarioId}/steps/${stepId}`, body),
  removeStep: (scenarioId: number, stepId: number) =>
    api.del<void>(`${SCEN}/${scenarioId}/steps/${stepId}`),
  reorderSteps: (scenarioId: number, stepIds: number[]) =>
    api.post<void>(`${SCEN}/${scenarioId}/steps/reorder`, { step_ids: stepIds }),

  // Аккаунты кампании
  accounts: (id: number) => api.get<CampaignAccount[]>(`${BASE}/${id}/accounts`),
  attach: (id: number, body: AttachAccountBody) =>
    api.post<CampaignAccount>(`${BASE}/${id}/accounts`, body),
  patchAccount: (id: number, accountId: number, body: CampaignAccountPatchBody) =>
    api.patch<CampaignAccount>(`${BASE}/${id}/accounts/${accountId}`, body),
  detach: (id: number, accountId: number) =>
    api.del<void>(`${BASE}/${id}/accounts/${accountId}`),

  // Цели
  targets: (id: number) => api.get<Target[]>(`${BASE}/${id}/targets`),
  addTargets: (id: number, raw_inputs: string[]) =>
    api.post<Target[]>(`${BASE}/${id}/targets`, { raw_inputs }),
  removeTarget: (id: number, targetId: number) =>
    api.del<void>(`${BASE}/${id}/targets/${targetId}`),

  // Чёрный список
  blacklist: (id: number) => api.get<BlacklistEntry[]>(`${BASE}/${id}/blacklist`),
  addBlacklist: (id: number, body: BlacklistCreateBody) =>
    api.post<BlacklistEntry>(`${BASE}/${id}/blacklist`, body),
  removeBlacklist: (id: number, entryId: number) =>
    api.del<void>(`${BASE}/${id}/blacklist/${entryId}`),

  // Готовность / статистика / логи
  readiness: (id: number) => api.get<CampaignReadiness>(`${BASE}/${id}/readiness`),
  stats: (id: number) => api.get<CampaignStats>(`${BASE}/${id}/stats`),
  logs: (id: number, params?: { status?: string; limit?: number; offset?: number }) => {
    const q = new URLSearchParams();
    if (params?.status) q.set("status", params.status);
    if (params?.limit != null) q.set("limit", String(params.limit));
    if (params?.offset != null) q.set("offset", String(params.offset));
    const qs = q.toString();
    return api.get<ExecutionLog[]>(`${BASE}/${id}/logs${qs ? `?${qs}` : ""}`);
  },

  // Жизненный цикл
  start: (id: number) => api.post<Campaign>(`${BASE}/${id}/start`),
  stop: (id: number) => api.post<Campaign>(`${BASE}/${id}/stop`),
  dryRun: (id: number, testTarget: string) =>
    api.post<{ job_id: string }>(
      `${BASE}/${id}/dry-run?test_target=${encodeURIComponent(testTarget)}`,
    ),
  dryRunStreamPath: (id: number, jobId: string) =>
    `${BASE}/${id}/dry-run/${jobId}/stream`,
};
