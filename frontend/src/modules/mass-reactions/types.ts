export type MassReactionStatus =
  | "draft"
  | "queued"
  | "running"
  | "paused"
  | "stopped"
  | "finished"
  | "failed";

export type ChatSourceMode = "by_subscriptions" | "explicit_list";
export type ReactionStrategy = "random" | "round_robin";
export type WarmupProfile = "cold" | "warm" | "hot";
export type HumanizerMode = "off" | "balanced" | "aggressive";
export type ChatNotifyMode = "notify_only" | "notify_and_join";
export type ChatState =
  | "pending"
  | "active"
  | "not_subscribed"
  | "joining"
  | "failed"
  | "disabled";

export interface MassReactionCampaign {
  id: number;
  name: string;
  status: MassReactionStatus;
  chat_source_mode: ChatSourceMode;
  reaction_emojis: string[];
  reaction_strategy: ReactionStrategy;
  every_n_message: number;
  probability_percent: number;
  first_n_in_burst: number;
  duration_hours: number;
  skip_messages_older_than_days: number;
  delay_between_reactions_sec_min: number;
  delay_between_reactions_sec_max: number;
  join_pause_sec: number;
  warmup_profile: WarmupProfile;
  humanizer_mode: HumanizerMode;
  daily_limit_per_account: number;
  max_chats_per_account: number;
  flood_wait_pause_sec: number;
  max_flood_waits_per_account: number;
  quiet_hours_start: number;
  quiet_hours_end: number;
  started_at: string | null;
  expires_at: string | null;
  created_at: string | null;
}

export interface MassReactionCampaignCreateBody {
  name: string;
  reaction_emojis: string[];
  chat_source_mode?: ChatSourceMode;
  reaction_strategy?: ReactionStrategy;
  every_n_message?: number;
  probability_percent?: number;
  first_n_in_burst?: number;
  duration_hours?: number;
  skip_messages_older_than_days?: number;
  delay_between_reactions_sec_min?: number;
  delay_between_reactions_sec_max?: number;
  join_pause_sec?: number;
  warmup_profile?: WarmupProfile;
  humanizer_mode?: HumanizerMode;
  daily_limit_per_account?: number;
  max_chats_per_account?: number;
  quiet_hours_start?: number;
  quiet_hours_end?: number;
}

export interface MassReactionChat {
  id: number;
  chat_ref: string;
  chat_tg_id: number | null;
  title: string | null;
  state: ChatState;
  notify_mode: ChatNotifyMode;
  account_id: number | null;
  reactions_total: number;
}

export interface MassReactionAccount {
  id: number;
  account_id: number;
  state: string;
  reactions_today: number;
  reactions_total: number;
}
