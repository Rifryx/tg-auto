/* Типы shilling-API (зеркало modules/shilling/schemas). */

export type LLMProvider = "deepseek" | "gemini";
export type CampaignStatus =
  | "draft"
  | "ready"
  | "running"
  | "paused"
  | "completed"
  | "error";
export type AutoResponderMode = "off" | "neuro_dialogs" | "reply_in_chat";
export type StepType = "message" | "reaction";
export type TargetKind = "username" | "invite" | "chat_id";
export type TargetStatus = "pending" | "resolved" | "error";
export type ExecutionStatus = "sent" | "failed" | "skipped" | "replaced";

export interface Campaign {
  id: number;
  name: string;
  brand_name: string | null;
  brand_link: string | null;
  topic: string | null;
  llm_provider: LLMProvider;
  unique_messages: boolean;
  use_chat_context: boolean;
  reply_delay_min_sec: number;
  reply_delay_max_sec: number;
  target_delay_min_sec: number;
  target_delay_max_sec: number;
  posts_per_target: number;
  scenario_id: number | null;
  media_asset_id: number | null;
  auto_responder: AutoResponderMode;
  reserve_enabled: boolean;
  msg_limit_per_hour: number | null;
  msg_limit_total: number | null;
  enabled: boolean;
  status: CampaignStatus;
  created_at: string;
  updated_at: string;
}

export interface CampaignCreateBody {
  name: string;
  brand_name?: string | null;
  brand_link?: string | null;
  topic?: string | null;
  llm_provider?: LLMProvider;
  unique_messages?: boolean;
  use_chat_context?: boolean;
  reply_delay_min_sec?: number;
  reply_delay_max_sec?: number;
  target_delay_min_sec?: number;
  target_delay_max_sec?: number;
  posts_per_target?: number;
  scenario_id?: number | null;
  media_asset_id?: number | null;
  auto_responder?: AutoResponderMode;
  reserve_enabled?: boolean;
  msg_limit_per_hour?: number | null;
  msg_limit_total?: number | null;
  enabled?: boolean;
}

export type CampaignUpdateBody = Partial<CampaignCreateBody> & {
  status?: CampaignStatus;
};

/* ── Сценарий, роли, шаги ─────────────────────────────────────────── */

export interface Scenario {
  id: number;
  campaign_id: number | null;
  name: string | null;
  is_template: boolean;
  persons_count: number;
  ai_generated: boolean;
  created_at: string;
  updated_at: string;
}

export interface ScenarioCreateBody {
  campaign_id?: number | null;
  name?: string | null;
  is_template?: boolean;
  persons_count?: number;
  ai_generated?: boolean;
}

export interface Role {
  id: number;
  scenario_id: number;
  name: string;
  character: string | null;
  color: string | null;
  sort_order: number;
}

export interface RoleCreateBody {
  name: string;
  character?: string | null;
  color?: string | null;
  sort_order?: number;
}
export type RoleUpdateBody = Partial<RoleCreateBody>;

export interface Step {
  id: number;
  scenario_id: number;
  role_id: number;
  step_order: number;
  step_type: StepType;
  text: string | null;
  reply_to_step_id: number | null;
  delay_before_sec: number | null;
  reaction_emoji: string | null;
}

export interface StepCreateBody {
  role_id: number;
  step_order?: number;
  step_type?: StepType;
  text?: string | null;
  reply_to_step_id?: number | null;
  delay_before_sec?: number | null;
  reaction_emoji?: string | null;
}
export type StepUpdateBody = Partial<Omit<StepCreateBody, "role_id">> & {
  role_id?: number;
};

/* ── ИИ-генерация ──────────────────────────────────────────────────── */

export interface GenerateRoleInput {
  name: string;
  character?: string;
}

export interface ScenarioGenerateBody {
  topic: string;
  brand_name?: string | null;
  persons_count?: number;
  steps_count?: number | null;
  roles?: GenerateRoleInput[] | null;
}

export interface GeneratedScenario {
  roles: { name: string; character: string }[];
  steps: { role: string; text: string; reply_to_step: number | null }[];
}

/* ── Аккаунты кампании ─────────────────────────────────────────────── */

export interface CampaignAccount {
  id: number;
  campaign_id: number;
  account_id: number;
  role_id: number | null;
  is_reserve: boolean;
  created_at: string;
}

export interface AttachAccountBody {
  account_id: number;
  role_id?: number | null;
  is_reserve?: boolean;
}
export interface CampaignAccountPatchBody {
  role_id?: number | null;
  is_reserve?: boolean;
}

/* ── Цели ──────────────────────────────────────────────────────────── */

export interface Target {
  id: number;
  campaign_id: number;
  raw_input: string;
  kind: TargetKind;
  resolved_chat_id: number | null;
  title: string | null;
  status: TargetStatus;
  last_error: string | null;
  created_at: string;
}

/* ── Чёрный список ─────────────────────────────────────────────────── */

export interface BlacklistEntry {
  id: number;
  campaign_id: number;
  chat_id: number | null;
  username: string | null;
  reason: string | null;
  auto: boolean;
  created_at: string;
  updated_at: string;
}

export interface BlacklistCreateBody {
  chat_id?: number | null;
  username?: string | null;
  reason?: string | null;
}

/* ── Логи, статистика, готовность ──────────────────────────────────── */

export interface ExecutionLog {
  id: number;
  campaign_id: number;
  target_id: number | null;
  account_id: number;
  role_id: number | null;
  step_id: number | null;
  message_text: string | null;
  posted_message_id: number | null;
  status: ExecutionStatus;
  error: string | null;
  created_at: string;
}

export interface CampaignStats {
  total: number;
  sent: number;
  failed: number;
  skipped: number;
  replaced: number;
  success_rate_percent: number;
}

export interface ReadinessCheck {
  ok: boolean;
  label: string;
  reason: string | null;
}

export interface CampaignReadiness {
  accounts: ReadinessCheck;
  scenario: ReadinessCheck;
  targets: ReadinessCheck;
  can_run: boolean;
}

/* ── Сухой прогон ──────────────────────────────────────────────────── */

export interface DryRunStep {
  step_id: number;
  account_id: number;
  role_name: string;
  text: string;
  scheduled_at_sec: number;
  risk_score: string;
}

export interface DryRunReport {
  job_id: string;
  ok: boolean;
  reason: string | null;
  timeline: DryRunStep[];
  total_messages: number;
  total_reactions: number;
  duration_sec: number;
  estimated_tokens: number;
}
