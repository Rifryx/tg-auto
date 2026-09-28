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
  status: PrimingCampaignStatus;
  started_at: string | null;
  finished_at: string | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
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
}
