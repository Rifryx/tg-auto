import { api } from "../../shared/api";
import type { ParsedList, ParsedListTarget, RunChatMessagesBody } from "./types";

const BASE = "/modules/parsing/lists";

export const parsingApi = {
  list: () => api.get<ParsedList[]>(BASE),
  get: (id: number) => api.get<ParsedList>(`${BASE}/${id}`),
  targets: (id: number) => api.get<ParsedListTarget[]>(`${BASE}/${id}/targets`),
  remove: (id: number) => api.del<void>(`${BASE}/${id}`),
  runChatMessages: (body: RunChatMessagesBody) =>
    api.post<{ job_id: string }>(`${BASE}/run/chat-messages`, body),
  runChatMembers: (body: {
    name: string;
    collector_account_id: number;
    chat_ref: string;
    only_recently_seen?: boolean;
    require_username?: boolean;
    premium_only?: boolean;
  }) => api.post<{ job_id: string }>(`${BASE}/run/chat-members`, body),
};
