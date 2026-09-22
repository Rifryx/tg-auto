/* API-клиент Autopilot (этап 13, UI для этапа 12).
 *
 * Типы соответствуют схемам core/schemas/autopilot.py. Три типа целей:
 *  - maintain_pool_size {target: N}   — держать N аккаунтов в pool;
 *  - keep_low_risk     {max_risk: X}  — средний ban_risk ниже X;
 *  - warmup_pipeline   {target: M}    — M аккаунтов одновременно в warming.
 */

import { api } from "./api";

export type GoalType =
  | "maintain_pool_size"
  | "keep_low_risk"
  | "warmup_pipeline";

export type AutopilotActionType =
  | "start_warming"
  | "retire_risky"
  | "throttle"
  | "noop";

export type AutopilotActionStatus =
  | "planned"
  | "executed"
  | "failed"
  | "skipped";

export interface Goal {
  id: number;
  user_id: string;
  goal_type: GoalType;
  params: Record<string, number>;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface AutopilotAction {
  id: number;
  goal_id: number;
  action_type: AutopilotActionType;
  account_id: number | null;
  status: AutopilotActionStatus;
  reason: string | null;
  meta: Record<string, unknown>;
  created_at: string;
}

export interface AutopilotStatus {
  goals: Goal[];
  recent_actions: AutopilotAction[];
}

export interface GoalCreate {
  goal_type: GoalType;
  params: Record<string, number>;
}

export interface GoalUpdate {
  params?: Record<string, number>;
  enabled?: boolean;
}

export const autopilotApi = {
  listGoals: () => api.get<Goal[]>("/autopilot/goals"),
  createGoal: (body: GoalCreate) => api.post<Goal>("/autopilot/goals", body),
  updateGoal: (id: number, body: GoalUpdate) =>
    api.patch<Goal>(`/autopilot/goals/${id}`, body),
  deleteGoal: (id: number) => api.del<void>(`/autopilot/goals/${id}`),
  status: () => api.get<AutopilotStatus>("/autopilot/status"),
};

export const GOAL_LABEL: Record<GoalType, string> = {
  maintain_pool_size: "Держать в пуле",
  keep_low_risk: "Низкий риск бана",
  warmup_pipeline: "Одновременно в прогреве",
};

export const GOAL_DESCRIPTION: Record<GoalType, string> = {
  maintain_pool_size:
    "Автоматически запускать прогрев новых аккаунтов, чтобы в пуле было не меньше указанного числа.",
  keep_low_risk:
    "Ретайрить критически рискованные (≥0.8) и снижать темп высокорискованных (≥0.6).",
  warmup_pipeline:
    "Держать указанное количество аккаунтов одновременно в состоянии прогрева.",
};

export const GOAL_PARAM_KEY: Record<GoalType, string> = {
  maintain_pool_size: "target",
  keep_low_risk: "max_risk",
  warmup_pipeline: "target",
};

export const ACTION_LABEL: Record<AutopilotActionType, string> = {
  start_warming: "Запуск прогрева",
  retire_risky: "Ретайр рискованного",
  throttle: "Снижение темпа",
  noop: "Без действия",
};
