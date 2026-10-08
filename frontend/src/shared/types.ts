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
export type AccountRole = "main" | "support" | "warmup" | "burner";
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
  project_id: number | null;
  role: AccountRole | null;
  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface Project {
  id: number;
  user_id: string;
  name: string;
  description: string | null;
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

/* Канал/супергруппа, созданная аккаунтом (project_channels). */
export interface ProjectChannel {
  id: number;
  account_id: number;
  project_id: number | null;
  channel_tg_id: number;
  channel_access_hash: number | null;
  title: string;
  username: string | null;
  is_megagroup: boolean;
  pinned_message_id: number | null;
  created_at: string;
}

/* ИИ-превью профиля (POST /accounts/{id}/profile/generate-preview). */
export interface ProfilePreview {
  first_name: string;
  last_name: string;
  bio: string;
  username_candidates: string[];
}

/* --- Bulk-задания (POST /bulk-jobs) --- */
export type BulkJobStatus = "queued" | "running" | "done" | "failed" | "cancelled";
export type BulkItemStatus =
  | "pending"
  | "running"
  | "done"
  | "failed"
  | "skipped"
  | "cancelled";

export interface BulkJobRead {
  id: number;
  action_type: string;
  payload: Record<string, unknown>;
  initiator: string;
  status: BulkJobStatus;
  total_count: number;
  done_count: number;
  failed_count: number;
  skipped_count: number;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface BulkJobItemRead {
  id: number;
  job_id: number;
  account_id: number;
  status: BulkItemStatus;
  error: string | null;
  result: Record<string, unknown> | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface BulkJobDetail {
  job: BulkJobRead;
  items: BulkJobItemRead[];
}

/* Запись журнала комментариев аккаунта (GET /accounts/{id}/comment-logs). */
export type CommentStatus = "posted" | "failed" | "flagged";
export interface CommentLog {
  id: number;
  campaign_id: number;
  account_id: number;
  post_channel_msg_id: number;
  posted_message_id: number | null;
  comment_text: string;
  in_reply_to_message_id: number | null;
  status: CommentStatus;
  error: string | null;
  created_at: string;
}

/* Ассет пула оформления (profile_assets) — распределяется apply_profile_pool. */
export type ProfileAssetKind =
  | "avatar"
  | "first_name"
  | "last_name"
  | "bio"
  | "username_template";
export interface ProfileAsset {
  id: number;
  kind: ProfileAssetKind;
  value: string | null;
  mime: string | null;
  tags: string[];
  description: string | null;
  used_count: number;
  created_at: string;
  has_binary: boolean;
}

/* Медиа-ассет (POST /media-assets) — источник для Stories/аватаров. */
export interface MediaAsset {
  id: number;
  mime: string;
  size_bytes: number;
  sha256: string;
  filename: string | null;
  created_at: string;
}

export interface ExportedSession {
  account_id: number;
  phone: string;
  session_string: string;
}

/* Кастомный сценарий прогрева (GET/PUT /accounts/{id}/warming-scenario).
   Любое поле null → наследуется от пресета интенсивности. */
export interface WarmingScenario {
  interval_hours_min: number | null;
  interval_hours_max: number | null;
  actions_min: number | null;
  actions_max: number | null;
  action_weights: Record<string, number> | null;
  ready_actions: number | null;
  ready_days: number | null;
}

export interface AccountHealth {
  account_id: number;
  health_score: number;
  session_alive: boolean | null;
  spam_blocked: boolean | null;
  spam_until: string | null;
  has_2fa: boolean | null;
  has_username: boolean | null;
  has_avatar: boolean | null;
  has_bio: boolean | null;
  age_days: number | null;
}
