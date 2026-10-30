/* Типы модуля parsing.  Соответствуют
   modules/parsing/schemas (Pydantic Read). */

export type ParserSourceKind =
  | "chat_messages"
  | "chat_members"
  | "manual_list"
  | "upload_csv"
  | "channel_commenters"
  | "post_reactors"
  | "list_op"
  | "community_enrich";

/* Общие фильтры аудитории (Extraction+, этап 1). */
export interface AudienceFilters {
  require_username?: boolean;
  premium_only?: boolean;
  require_photo?: boolean;
  verified_only?: boolean;
  exclude_scam_fake?: boolean;
  require_phone_visible?: boolean;
  username_regex?: string | null;
  name_script?: "cyrillic" | "latin" | null;
  last_seen_max_days?: number | null;
  /** Фильтр по стране телефонного номера: список префиксов (+380, +7, …). */
  phone_country_prefixes?: string[] | null;
}

export type LastSeenBucket =
  | "recently"
  | "within_week"
  | "within_month"
  | "long_ago"
  | "unknown";

export interface ParsedList {
  id: number;
  owner_user_id: number;
  name: string;
  source_kind: ParserSourceKind;
  chat_ref: string | null;
  days_window: number | null;
  min_messages: number | null;
  raw_count: number;
  after_filters_count: number;
  filters_breakdown: Record<string, number>;
  parsed_at: string | null;
  created_at: string;
}

export interface ParsedListTarget {
  id: number;
  list_id: number;
  tg_user_id: number | null;
  username: string | null;
  phone: string | null;
  has_premium: boolean | null;
  first_name: string | null;
  last_name: string | null;
  photo_url: string | null;
  last_seen_bucket: LastSeenBucket;
  created_at: string;
}

export type ParsingJobStatus =
  | "pending"
  | "running"
  | "paused"
  | "done"
  | "failed"
  | "stopped";

export interface ParsingJobLogLine {
  ts: string;
  msg: string;
}

export interface ParsingJob {
  id: number;
  owner_user_id: number;
  kind: string;
  name: string;
  status: ParsingJobStatus;
  control: "run" | "pause" | "stop";
  log: ParsingJobLogLine[];
  raw_count: number;
  inserted_count: number;
  list_id: number | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface RunChatMessagesBody extends AudienceFilters {
  name: string;
  collector_account_id: number;
  chat_ref: string;
  days_window?: number;
  min_messages?: number;
  max_targets?: number | null;
}

export interface RunChatMembersBody extends AudienceFilters {
  name: string;
  collector_account_id: number;
  chat_ref: string;
  only_recently_seen?: boolean;
  max_targets?: number | null;
}

export interface RunPostReactorsBody extends AudienceFilters {
  name: string;
  collector_account_id: number;
  chat_ref: string;
  posts_limit?: number;
  reactions_per_post?: number;
  min_reactions?: number;
  max_targets?: number | null;
}

/* Discovery сообществ (этап 2). */
export interface CommunityItem {
  id: number;
  list_id: number;
  input_ref: string;
  channel_tg_id: number | null;
  title: string | null;
  username: string | null;
  is_public: boolean;
  kind: "channel" | "chat";
  participants_count: number | null;
  has_linked_chat: boolean;
  last_post_at: string | null;
  is_verified: boolean;
  is_scam: boolean;
  is_fake: boolean;
  slowmode_seconds: number | null;
  about: string | null;
  created_at: string;
}

/** Расширенные фильтры каналов/чатов (общие для enrich и discover). */
export interface CommunityExtraFilters {
  title_exclude_regex?: string | null;
  /** "ru" / "en" / "ru_or_en" / null. Язык определяется по title+about. */
  language?: "ru" | "en" | "ru_or_en" | null;
  /** false → отсеивать каналы c noforwards (запрет пересылки). */
  allow_noforwards?: boolean;
  min_slowmode_seconds?: number | null;
  max_slowmode_seconds?: number | null;
}

export interface RunCommunitiesBody extends CommunityExtraFilters {
  name: string;
  collector_account_id: number;
  refs: string[];
  kind?: "channel" | "chat" | null;
  min_participants?: number | null;
  max_participants?: number | null;
  require_public?: boolean;
  require_linked_chat?: boolean;
  last_post_max_days?: number | null;
  exclude_scam_fake?: boolean;
  verified_only?: boolean;
  title_regex?: string | null;
  username_regex?: string | null;
}

/* Бесплатный нативный discovery сообществ (поиск + похожие + snowball). */
export interface RunDiscoverBody extends CommunityExtraFilters {
  name: string;
  collector_account_id: number;
  seeds: string[];
  term?: string | null;
  use_search?: boolean;
  use_recommendations?: boolean;
  use_forwards?: boolean;
  use_mentions?: boolean;
  depth?: number;
  max_results?: number;
  kind?: "channel" | "chat" | null;
  min_participants?: number | null;
  max_participants?: number | null;
  require_public?: boolean;
  require_linked_chat?: boolean;
  last_post_max_days?: number | null;
  exclude_scam_fake?: boolean;
  verified_only?: boolean;
  title_regex?: string | null;
  username_regex?: string | null;
}

export type ListOp = "intersect" | "union" | "subtract" | "sample";

export interface ListOpBody {
  name: string;
  op: ListOp;
  source_list_ids: number[];
  min_overlap?: number | null;
  sample_size?: number | null;
}
