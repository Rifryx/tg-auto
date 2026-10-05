/* Типы модуля parsing.  Соответствуют
   modules/parsing/schemas (Pydantic Read). */

export type ParserSourceKind =
  | "chat_messages"
  | "chat_members"
  | "manual_list"
  | "upload_csv"
  | "channel_commenters"
  | "post_reactors"
  | "list_op";

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
  last_seen_bucket: LastSeenBucket;
  created_at: string;
}

export interface RunChatMessagesBody extends AudienceFilters {
  name: string;
  collector_account_id: number;
  chat_ref: string;
  days_window?: number;
  min_messages?: number;
}

export interface RunChatMembersBody extends AudienceFilters {
  name: string;
  collector_account_id: number;
  chat_ref: string;
  only_recently_seen?: boolean;
}

export interface RunPostReactorsBody extends AudienceFilters {
  name: string;
  collector_account_id: number;
  chat_ref: string;
  posts_limit?: number;
  reactions_per_post?: number;
  min_reactions?: number;
}

export type ListOp = "intersect" | "union" | "subtract" | "sample";

export interface ListOpBody {
  name: string;
  op: ListOp;
  source_list_ids: number[];
  min_overlap?: number | null;
  sample_size?: number | null;
}
