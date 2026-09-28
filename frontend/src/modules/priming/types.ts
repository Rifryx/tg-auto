/* Типы модуля прайминга. Соответствуют
   modules/priming/schemas/campaign.py (Pydantic Read). */

export type PrimingCampaignStatus =
  | "draft"
  | "queued"
  | "running"
  | "paused"
  | "stopped"
  | "finished"
  | "failed";

export type PrimingTriggerAction =
  | "set_ttl_1d"
  | "set_ttl_off"
  | "set_content_protection"
  | "secret_chat_request"
  | "contact_added"
  | "contact_removed"
  | "pinned_message_ping";

export type HumanizerMode = "off" | "balanced" | "aggressive";
export type WarmupProfile = "cold" | "warm" | "hot";
export type TriggerRotationStrategy = "random" | "round_robin" | "weighted";

export interface PrimingCampaign {
  id: number;
  name: string;
  mode: "priming";
  trigger_action: PrimingTriggerAction;
  trigger_actions: PrimingTriggerAction[];
  trigger_rotation_strategy: TriggerRotationStrategy;
  humanizer_mode: HumanizerMode;
  warmup_profile: WarmupProfile;
  delay_between_targets_sec_min: number;
  delay_between_targets_sec_max: number;
  flood_wait_pause_sec: number;
  max_flood_waits_per_account: number;
  daily_limit_per_account: number;
  require_username: boolean;
  premium_only: boolean;
  exclude_bots: boolean;
  exclude_deleted: boolean;
  exclude_admins: boolean;
  stop_on_privacy_rate: number;
  dry_run: boolean;
  quiet_hours_target: boolean;
  quiet_hours_tz: string | null;
  status: PrimingCampaignStatus;
  started_at: string | null;
  finished_at: string | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export type PrimingExecutionOutcome =
  | "primed"
  | "already_applied"
  | "flood_wait"
  | "privacy_restricted"
  | "deleted"
  | "not_found"
  | "channel_pinned_error"
  | "skipped_quiet"
  | "internal_error";

export interface PrimingLogRow {
  id: number;
  started_at: string;
  finished_at: string;
  account_id: number;
  target_id: number;
  outcome: PrimingExecutionOutcome;
  trigger_action: PrimingTriggerAction;
  latency_ms: number;
  error_code: string | null;
  flood_wait_sec: number | null;
  dry_run: boolean;
}

export interface PrimingLogsPage {
  items: PrimingLogRow[];
  next_cursor: number | null;
}

export interface PrimingLiveAccountRow {
  id: number;
  account_id: number;
  state: "idle" | "working" | "cooldown" | "quarantined" | "disabled";
  primes_today: number;
  primes_total: number;
  flood_waits_consecutive: number;
  last_prime_at: string | null;
  next_available_at: string | null;
}

export interface PrimingLiveSnapshot {
  status: PrimingCampaignStatus;
  dry_run: boolean;
  counters: Record<string, number>;
  sparkline_24h: number[];
  accounts: PrimingLiveAccountRow[];
}

export interface PrimingCampaignCreateBody {
  name: string;
  trigger_action: PrimingTriggerAction;
  trigger_actions?: PrimingTriggerAction[];
  trigger_rotation_strategy?: TriggerRotationStrategy;
  humanizer_mode?: HumanizerMode;
  warmup_profile?: WarmupProfile;
  delay_between_targets_sec_min?: number;
  delay_between_targets_sec_max?: number;
  daily_limit_per_account?: number;
  dry_run?: boolean;
  quiet_hours_target?: boolean;
  quiet_hours_tz?: string | null;
}
