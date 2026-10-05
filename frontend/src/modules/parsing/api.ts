import { api } from "../../shared/api";
import type {
  CatalogCandidate,
  CatalogSearchBody,
  CommunityItem,
  ListOpBody,
  ParsedList,
  ParsedListTarget,
  RunChatMembersBody,
  RunChatMessagesBody,
  RunCommunitiesBody,
  RunPostReactorsBody,
} from "./types";

const BASE = "/modules/parsing/lists";

export const parsingApi = {
  list: () => api.get<ParsedList[]>(BASE),
  get: (id: number) => api.get<ParsedList>(`${BASE}/${id}`),
  targets: (id: number) => api.get<ParsedListTarget[]>(`${BASE}/${id}/targets`),
  remove: (id: number) => api.del<void>(`${BASE}/${id}`),
  runChatMessages: (body: RunChatMessagesBody) =>
    api.post<{ job_id: string }>(`${BASE}/run/chat-messages`, body),
  runChatMembers: (body: RunChatMembersBody) =>
    api.post<{ job_id: string }>(`${BASE}/run/chat-members`, body),
  runChannelCommenters: (body: RunChatMessagesBody) =>
    api.post<{ job_id: string }>(`${BASE}/run/channel-commenters`, body),
  runPostReactors: (body: RunPostReactorsBody) =>
    api.post<{ job_id: string }>(`${BASE}/run/post-reactors`, body),
  runCommunities: (body: RunCommunitiesBody) =>
    api.post<{ job_id: string }>(`${BASE}/run/communities`, body),
  communities: (id: number) =>
    api.get<CommunityItem[]>(`${BASE}/${id}/communities`),
  listOps: (body: ListOpBody) => api.post<ParsedList>(`${BASE}/ops`, body),
  catalogStatus: (provider = "telemetrio") =>
    api.get<{ provider: string; ok: boolean; usage: Record<string, unknown> }>(
      `/modules/parsing/catalog/status?provider=${provider}`,
    ),
  catalogSearch: (body: CatalogSearchBody) =>
    api.post<CatalogCandidate[]>(`/modules/parsing/catalog/search`, body),
};
