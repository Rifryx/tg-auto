/* Типы commenting-API (зеркало modules/commenting/schemas). */

export type LLMProvider = "deepseek" | "gemini";
export type CommentStatus = "posted" | "failed" | "flagged";

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
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface CampaignAccount {
  campaign_id: number;
  account_id: number;
  override_prompt: string | null;
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
  enabled?: boolean;
}

export type CampaignUpdateBody = Partial<CampaignCreateBody>;
