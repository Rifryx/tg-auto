import { api } from "../../shared/api";

export interface Alert {
  id: number;
  account_id: number;
  phone: string | null;
  event_type: string;
  severity: string; // "warning" | "critical"
  created_at: string | null;
  meta: Record<string, unknown> | null;
}

export interface AccountsSummary {
  created: number;
  warming: number;
  pool: number;
  assigned: number;
  cooldown: number;
  retired: number;
  banned: number;
}

export interface ModuleSummary {
  module: string;
  instances: number;
  active_now: number;
  today_actions: number;
}

export interface ActivityItem {
  type: string;
  account_id: number;
  phone: string | null;
  display_name: string | null;
  action_type?: string;
  summary: string;
  detail?: string;
  status?: string;
  timestamp: string | null;
}

export interface Kpis {
  actions_today: number;
  errors_today: number;
  active_campaigns: number;
  paused_campaigns: number;
  accounts_working: number;
}

export interface TrendPoint {
  date: string; // ISO date (YYYY-MM-DD), UTC
  actions: number;
}

export interface Dashboard {
  alerts: Alert[];
  accounts_summary: AccountsSummary;
  modules_summary: ModuleSummary[];
  kpis: Kpis;
  trend_7d: TrendPoint[];
  recent_activity: ActivityItem[];
}

export const dashboardApi = {
  get: () => api.get<Dashboard>("/monitoring/dashboard"),
};
