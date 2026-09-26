/* Типы commenting-API (зеркало modules/commenting/schemas). */

export type LLMProvider = "deepseek" | "gemini";
export type CommentStatus = "posted" | "failed" | "flagged";
export type PostSelectionMode = "all" | "keywords" | "probability";
export type PostScope = "new" | "existing" | "mixed";
export type WorkMode = "by_count" | "by_time_window";
export type ChannelSourceMode = "by_account_subscriptions" | "explicit_links";
export type OnNotSubscribedAction = "subscribe_and_notify" | "notify_only";
export type ChannelKind = "username" | "invite" | "folder";

export interface Campaign {
  id: number;
  name: string;
  target_channel: string | null;
  discussion_group_id: number | null;
  base_system_prompt: string;
  persona_id: number | null;
  llm_provider: LLMProvider;
  active_hours_start: string; // "HH:MM:SS"
  active_hours_end: string;
  active_hours_tz: string;
  posting_delay_min_sec: number;
  posting_delay_max_sec: number;
  join_delay_min_sec: number;
  join_delay_max_sec: number;
  floodwait_pause_sec: number;
  floodwait_quarantine_max: number;
  enabled: boolean;
  post_selection_mode: PostSelectionMode;
  keywords: string[];
  probability_percent: number;
  post_scope: PostScope;
  work_mode: WorkMode;
  max_comments: number | null;
  min_words: number;
  window_after_post_sec: number | null;
  pause_between_sec: number | null;
  channel_source_mode: ChannelSourceMode;
  on_not_subscribed_action: OnNotSubscribedAction;
  use_emojis: boolean;
  use_stickers: boolean;
  attach_image: boolean;
  write_as_channel: boolean;
  verify_after_post: boolean;
  verify_delay_sec: number;
  created_at: string;
  updated_at: string;
}

export interface CampaignAccount {
  campaign_id: number;
  account_id: number;
  override_prompt: string | null;
  probability_override: number | null;
  created_at: string;
}

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

export interface CampaignCreateBody {
  name: string;
  target_channel?: string | null;
  base_system_prompt: string;
  persona_id?: number | null;
  llm_provider: LLMProvider;
  active_hours_start: string;
  active_hours_end: string;
  active_hours_tz: string;
  posting_delay_min_sec: number;
  posting_delay_max_sec: number;
  join_delay_min_sec?: number;
  join_delay_max_sec?: number;
  floodwait_pause_sec?: number;
  floodwait_quarantine_max?: number;
  enabled?: boolean;
  post_selection_mode?: PostSelectionMode;
  keywords?: string[];
  probability_percent?: number;
  post_scope?: PostScope;
  work_mode?: WorkMode;
  max_comments?: number | null;
  min_words?: number;
  window_after_post_sec?: number | null;
  pause_between_sec?: number | null;
  channel_source_mode?: ChannelSourceMode;
  on_not_subscribed_action?: OnNotSubscribedAction;
  use_emojis?: boolean;
  use_stickers?: boolean;
  attach_image?: boolean;
  write_as_channel?: boolean;
  verify_after_post?: boolean;
  verify_delay_sec?: number;
}

export interface CampaignChannel {
  id: number;
  campaign_id: number;
  raw_input: string;
  kind: ChannelKind;
  resolved_chat_id: number | null;
  title: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChannelBlacklistEntry {
  id: number;
  campaign_id: number;
  chat_id: number | null;
  username: string | null;
  reason: string | null;
  auto: boolean;
  created_at: string;
  updated_at: string;
}

export interface CampaignAccountPatchBody {
  override_prompt?: string | null;
  probability_override?: number | null;
}

/* ── ИИ-защита аккаунтов (§ Этап 5) ────────────────────────────────── */

export type AiProtectionFeatureStatus = "active" | "degraded" | "off";

export interface AiProtectionFeature {
  key: string;
  label: string;
  description: string;
  status: AiProtectionFeatureStatus;
}

export interface AccountRiskBucket {
  low: number;
  medium: number;
  high: number;
  critical: number;
  unknown: number;
}

export interface AiProtectionStatus {
  active: boolean;
  features: AiProtectionFeature[];
  accounts_by_risk: AccountRiskBucket;
  total_accounts: number;
}

/* ── Статистика и runtime-сводка (§ Этап 6) ─────────────────────────── */

export interface CampaignStats {
  total: number;
  posted: number;
  failed: number;
  flagged: number;
  success_rate_percent: number;
}

export interface CampaignRuntimeSummary {
  accounts_count: number;
  channels_count: number;
  max_interval_sec: number;
  max_comments: number | null;
  enabled: boolean;
}

export type CampaignUpdateBody = Partial<CampaignCreateBody>;

/* ── Пресеты (§ Этап 1) ──────────────────────────────────────────────── */

export interface AccountPreset {
  id: number;
  owner_user_id: string;
  name: string;
  account_ids: number[];
  created_at: string;
  updated_at: string;
}

export interface AccountPresetCreateBody {
  name: string;
  account_ids: number[];
}
export type AccountPresetUpdateBody = Partial<AccountPresetCreateBody>;

export interface DelayPreset {
  id: number;
  owner_user_id: string | null;
  name: string;
  is_system: boolean;
  posting_delay_min_sec: number;
  posting_delay_max_sec: number;
  join_delay_min_sec: number;
  join_delay_max_sec: number;
  floodwait_pause_sec: number;
  floodwait_quarantine_max: number;
  created_at: string;
  updated_at: string;
}

export interface DelayPresetCreateBody {
  name: string;
  posting_delay_min_sec: number;
  posting_delay_max_sec: number;
  join_delay_min_sec: number;
  join_delay_max_sec: number;
  floodwait_pause_sec: number;
  floodwait_quarantine_max: number;
}
export type DelayPresetUpdateBody = Partial<DelayPresetCreateBody>;

/* ── Алерты целевых каналов (E3.2) ──────────────────────────────────── */

export type ChannelAlertKind = "not_subscribed" | "auto_subscribed" | "access_lost" | "blacklisted";

export interface ChannelAlert {
  id: number;
  campaign_id: number | null;
  account_id: number;
  channel_ref: string;
  kind: ChannelAlertKind;
  detail: string | null;
  resolved: boolean;
  created_at: string;
}
