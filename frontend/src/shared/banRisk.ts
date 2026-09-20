/* API-клиент Anti-Ban Predictor (этап 13, UI для этапа 11). */

import { api } from "./api";

export type RiskLevel = "low" | "medium" | "high" | "critical";

export interface BanRiskContribution {
  factor: string;
  contribution: number;
}

export interface BanRisk {
  account_id: number;
  risk_score: number;
  risk_level: RiskLevel;
  previous_risk_score: number | null;
  features: Record<string, unknown>;
  contributions: BanRiskContribution[];
  computed_at: string | null;
}

export const banRiskApi = {
  get: (accountId: number) => api.get<BanRisk>(`/ban-risk/${accountId}`),
  listHighRisk: (params: { min_score?: number; limit?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.min_score !== undefined) qs.set("min_score", String(params.min_score));
    if (params.limit !== undefined) qs.set("limit", String(params.limit));
    const query = qs.toString();
    return api.get<BanRisk[]>(`/ban-risk/${query ? `?${query}` : ""}`);
  },
};

export const RISK_LEVEL_LABEL: Record<RiskLevel, string> = {
  low: "Низкий",
  medium: "Средний",
  high: "Высокий",
  critical: "Критический",
};

/** Возвращает CSS-класс фона под уровень риска (Tailwind + токены темы). */
export function riskLevelBgClass(level: RiskLevel): string {
  switch (level) {
    case "critical":
      return "bg-danger/15 text-danger";
    case "high":
      return "bg-warning/15 text-warning";
    case "medium":
      return "bg-warning/10 text-text-primary";
    case "low":
    default:
      return "bg-success/10 text-success";
  }
}

export function riskDotClass(level: RiskLevel): string {
  switch (level) {
    case "critical":
      return "bg-danger";
    case "high":
      return "bg-warning";
    case "medium":
      return "bg-warning/60";
    case "low":
    default:
      return "bg-success";
  }
}

const FACTOR_LABEL: Record<string, string> = {
  session_dead: "Сессия мертва",
  phone_banned: "Телефон забанен",
  flood_waits_24h: "Flood-wait за 24ч",
  flood_waits_7d: "Flood-wait за 7д",
  spam_blocks_7d: "Спам-блоки за 7д",
  spam_blocks_30d: "Спам-блоки за 30д",
  action_fail_rate_24h: "Отказы действий 24ч",
  action_fail_rate_7d: "Отказы действий 7д",
  actions_per_hour_24h: "Интенсивность (акт/ч)",
  unique_action_types_7d: "Разнообразие действий",
  profile_completeness: "Заполненность профиля",
  age_days: "Возраст аккаунта",
  hours_since_last_incident: "Часов с инцидента",
  unresolved_incidents: "Открытые инциденты",
};

export function factorLabel(factor: string): string {
  return FACTOR_LABEL[factor] ?? factor;
}
