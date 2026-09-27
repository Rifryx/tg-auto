/* Типы модуля parsing.  Соответствуют
   modules/parsing/schemas (Pydantic Read). */

export type ParserSourceKind =
  | "chat_messages"
  | "chat_members"
  | "manual_list"
  | "upload_csv";

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

export interface RunChatMessagesBody {
  name: string;
  collector_account_id: number;
  chat_ref: string;
  days_window?: number;
  min_messages?: number;
  require_username?: boolean;
  premium_only?: boolean;
}
