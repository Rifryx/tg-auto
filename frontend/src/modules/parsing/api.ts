import { api } from "../../shared/api";
import type {
  CommunityItem,
  ListOpBody,
  ParsedList,
  ParsedListTarget,
  ParsingJob,
  RunChatMembersBody,
  RunChatMessagesBody,
  RunCommunitiesBody,
  RunDiscoverBody,
  RunPostReactorsBody,
} from "./types";

const BASE = "/modules/parsing/lists";

export const parsingApi = {
  list: () => api.get<ParsedList[]>(BASE),
  get: (id: number) => api.get<ParsedList>(`${BASE}/${id}`),
  targets: (id: number) => api.get<ParsedListTarget[]>(`${BASE}/${id}/targets`),
  remove: (id: number) => api.del<void>(`${BASE}/${id}`),
  runChatMessages: (body: RunChatMessagesBody) =>
    api.post<{ job_id: number }>(`${BASE}/run/chat-messages`, body),
  runChatMembers: (body: RunChatMembersBody) =>
    api.post<{ job_id: number }>(`${BASE}/run/chat-members`, body),
  runChannelCommenters: (body: RunChatMessagesBody) =>
    api.post<{ job_id: number }>(`${BASE}/run/channel-commenters`, body),
  runPostReactors: (body: RunPostReactorsBody) =>
    api.post<{ job_id: number }>(`${BASE}/run/post-reactors`, body),
  runCommunities: (body: RunCommunitiesBody) =>
    api.post<{ job_id: number }>(`${BASE}/run/communities`, body),
  runDiscover: (body: RunDiscoverBody) =>
    api.post<{ job_id: number }>(`${BASE}/run/discover`, body),
  communities: (id: number) =>
    api.get<CommunityItem[]>(`${BASE}/${id}/communities`),
  listOps: (body: ListOpBody) => api.post<ParsedList>(`${BASE}/ops`, body),
  // Прогресс/управление задачей парсинга.
  job: (jobId: number) => api.get<ParsingJob>(`/modules/parsing/jobs/${jobId}`),
  jobs: () => api.get<ParsingJob[]>(`/modules/parsing/jobs`),
  controlJob: (jobId: number, action: "pause" | "resume" | "stop") =>
    api.post<ParsingJob>(`/modules/parsing/jobs/${jobId}/control`, { action }),
};
