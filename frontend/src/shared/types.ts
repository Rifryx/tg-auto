/* Типы API (зеркало core/schemas). Только то, что нужно фронту. */

export type AccountStatus =
  | "created"
  | "warming"
  | "pool"
  | "assigned"
  | "cooldown"
  | "retired"
  | "banned";

export type WarmingProfile = "minimal" | "medium" | "dense";
export type ProxyStatus = "alive" | "dead" | "unchecked";
export type ProxyType = "socks5" | "http";
export type Initiator = "user" | "auto" | "health";
export type WarmingActivityKind = "initial" | "maintenance";
export type WarmingActivityStatus = "done" | "failed" | "skipped";
export type WarmingActionType =
  | "subscribe_channel"
  | "read_history"
  | "reaction"
  | "view_media"
  | "join_group"
  | "idle_online"
  | "update_profile";
export type LoginState =
  | "waiting_code"
  | "waiting_password"
  | "success"
  | "failed"
  | "rate_limited";

export interface Account {
  id: number;
  phone: string;
  first_name: string | null;
  last_name: string | null;
  username: string | null;
  bio: string | null;
  avatar_url: string | null;
  proxy_id: number | null;
  persona_id: number | null;
  status: AccountStatus;
  previous_status: AccountStatus | null;
  assigned_container_type: string | null;
  assigned_container_id: number | null;
  warming_profile: WarmingProfile;
  warming_started_at: string | null;
  activated_at: string | null;
  cooldown_until: string | null;
  device_model: string;
  system_version: string;
  app_version: string;
  lang_code: string;
  system_lang_code: string;
  created_at: string;
  updated_at: string;
}

export type MonitoredChannelStatus = "pending" | "working" | "paused" | "failed";

export interface MonitoredChannel {
  id: number;
  account_id: number;
  input_ref: string;
  is_folder: boolean;
  channel_ref: string | null;
  channel_tg_id: number | null;
  title: string | null;
  discussion_group_id: number | null;
  status: MonitoredChannelStatus;
  subscribed: boolean;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface StatusHistoryRecord {
  id: number;
  account_id: number;
  from_status: AccountStatus | null;
  to_status: AccountStatus;
  reason: string;
  initiator: Initiator;
  meta: Record<string, unknown> | null;
  created_at: string;
}

export interface WarmingActivity {
  id: number;
  account_id: number;
  kind: WarmingActivityKind;
  action_type: WarmingActionType;
  target: string | null;
  status: WarmingActivityStatus;
  meta: Record<string, unknown> | null;
  created_at: string;
}

export interface Proxy {
  id: number;
  host: string;
  port: number;
  login: string | null;
  type: ProxyType;
  geo: string | null;
  status: ProxyStatus;
  last_checked_at: string | null;
}

export interface Persona {
  id: number;
  name: string;
  avatar_template_url: string | null;
  bio_template: string | null;
  personality_tags: string[];
}

export interface LoginStateResponse {
  account_id: number;
  state: LoginState | null;
  reason: string | null;
  updated_at: string | null;
}
