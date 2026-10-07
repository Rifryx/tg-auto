import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, BadgeCheck, MessageSquare, Radio, Users } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { timeAgo } from "../../shared/format";
import { parsingApi } from "./api";
import type { CommunityItem } from "./types";

/* Детальный просмотр списка обогащённых сообществ (этап 2). */
export function CommunityListScreen() {
  const navigate = useNavigate();
  const { id } = useParams();
  const listId = Number(id);

  const items = useQuery({
    queryKey: ["parsing", "communities", listId],
    queryFn: () => parsingApi.communities(listId),
    enabled: Number.isFinite(listId),
  });

  const rows = items.data ?? [];

  return (
    <div className="min-h-full pb-10">
      <ScreenHeader
        title="Сообщества"
        action={
          <button
            type="button"
            onClick={() => navigate("/modules/parsing")}
            className="inline-flex h-9 items-center gap-1.5 rounded-pill bg-surface-2 px-4 text-[14px] text-text-secondary active:text-text-primary"
          >
            <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
            К спискам
          </button>
        }
      />

      {items.isLoading && (
        <div className="flex flex-col gap-2">
          {[0, 1, 2].map((i) => <div key={i} className="card h-20 animate-pulse bg-surface-2" />)}
        </div>
      )}
      {rows.length === 0 && !items.isLoading && (
        <p className="text-[14px] text-text-tertiary">В этом списке нет сообществ.</p>
      )}

      <div className="flex flex-col gap-2">
        {rows.map((c) => <CommunityRow key={c.id} c={c} />)}
      </div>
    </div>
  );
}

function CommunityRow({ c }: { c: CommunityItem }) {
  const Icon = c.kind === "chat" ? MessageSquare : Radio;
  return (
    <div className="card flex items-start gap-3 p-4">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-surface-2 text-text-primary">
        <Icon className="h-5 w-5" strokeWidth={1.7} aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <h3 className="truncate text-[15px] font-semibold text-text-primary">
            {c.title ?? c.input_ref}
          </h3>
          {c.is_verified && <BadgeCheck className="h-4 w-4 shrink-0 text-accent" strokeWidth={2} aria-hidden />}
          {(c.is_scam || c.is_fake) && (
            <span className="rounded-pill bg-status-critical/15 px-1.5 text-[10px] font-semibold uppercase text-status-critical">
              {c.is_scam ? "scam" : "fake"}
            </span>
          )}
        </div>
        <p className="truncate text-[13px] text-text-tertiary">
          {c.username ? `@${c.username}` : "приватный"} · {c.kind === "chat" ? "чат" : "канал"}
          {c.has_linked_chat ? " · с обсуждением" : ""}
        </p>
        <p className="mt-0.5 text-[12px] text-text-tertiary">
          {c.last_post_at ? `посл. пост ${timeAgo(c.last_post_at)}` : "постов не видно"}
        </p>
      </div>
      <div className="shrink-0 text-right">
        <div className="flex items-center gap-1 text-[16px] font-bold tabular-nums text-text-primary">
          <Users className="h-3.5 w-3.5 text-text-tertiary" strokeWidth={2} aria-hidden />
          {c.participants_count != null ? fmt(c.participants_count) : "—"}
        </div>
      </div>
    </div>
  );
}

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}
