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
};
