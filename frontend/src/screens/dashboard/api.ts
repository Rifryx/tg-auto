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
  summary: string;
  timestamp: string | null;
}

export interface Dashboard {
  alerts: Alert[];
  accounts_summary: AccountsSummary;
  modules_summary: ModuleSummary[];
  recent_activity: ActivityItem[];
}

export const dashboardApi = {
  get: () => api.get<Dashboard>("/monitoring/dashboard"),
};
