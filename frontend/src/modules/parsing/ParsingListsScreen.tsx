import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronRight,
  Combine,
  Filter,
  Loader2,
  Pause,
  Sparkles,
  Trash2,
  UserSearch,
} from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { EmptyState } from "../../components/EmptyState";
import { timeAgo } from "../../shared/format";
import { parsingApi } from "./api";
import type { ParsedList, ParsingJob } from "./types";

/* Модуль «Парсинг» — самостоятельный сервис (docs/priming-spec §8).
   Хранит спарсенные списки; Прайминг импортирует их через
   POST /modules/priming/campaigns/:id/targets/import-list. */

const SOURCE_LABEL: Record<ParsedList["source_kind"], string> = {
  chat_messages: "Сообщения чата",
  chat_members: "Участники чата",
  manual_list: "Ручной список",
  upload_csv: "CSV",
  channel_commenters: "Комментаторы канала",
  post_reactors: "Реакторы постов",
  list_op: "Операция над списками",
  community_enrich: "Сообщества (каналы/чаты)",
};

export function ParsingListsScreen() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [confirmDelete, setConfirmDelete] = useState<ParsedList | null>(null);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["parsing", "lists"],
    queryFn: parsingApi.list,
    refetchInterval: 10_000,
  });
  // Активные задачи — не блокируют UI, обновляются быстрее основного списка,
  // чтобы индикатор «идёт прогон» появлялся сразу после запуска.
  const activeJobs = useQuery({
    queryKey: ["parsing", "jobs"],
    queryFn: parsingApi.jobs,
    refetchInterval: 3_000,
    staleTime: 2_000,
  });
  const liveJobs = (activeJobs.data ?? []).filter(
    (j) => j.status === "running" || j.status === "paused" || j.status === "pending",
  );

  const remove = useMutation({
    mutationFn: (id: number) => parsingApi.remove(id),
    onSuccess: () => {
      setConfirmDelete(null);
      qc.invalidateQueries({ queryKey: ["parsing", "lists"] });
    },
  });

  return (
    <div className="min-h-full pb-24">
      <ScreenHeader title="Парсинг" />

      {/* Активные прогоны — список запущенных задач, которые крутятся в
          воркере даже если юзер ушёл со страницы (persistence). Каждая строка
          кликабельна → экран живого прогресса. Так пользователь всегда видит,
          что происходит, и не теряет текущие прогоны между переходами. */}
      {liveJobs.length > 0 && (
        <div className="mb-4 flex flex-col gap-2">
          <p className="px-1 text-[11px] font-semibold uppercase tracking-wider text-text-tertiary">
            Активные прогоны · {liveJobs.length}
          </p>
          <div className="card overflow-hidden p-0">
            {liveJobs.map((j, i) => (
              <ActiveJobRow
                key={j.id}
                job={j}
                isFirst={i === 0}
                onClick={() => navigate(`/modules/parsing/run/${j.id}`)}
              />
            ))}
          </div>
        </div>
      )}

      {/* Три равноправных вида парсинга — одной линией. Раньше «Прогон»
          (парсинг пользователей) был акцент-кнопкой справа в заголовке, а
          остальные — вторичными табами внизу: пользователь не понимал,
          что это ТОЖЕ парсер, и жаловался «тут нет парсинга пользователей». */}
      <div className="-mx-5 mb-4 flex gap-2 overflow-x-auto px-5 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <button
          type="button"
          onClick={() => navigate("/modules/parsing/run")}
          className="inline-flex h-10 shrink-0 items-center gap-1.5 rounded-pill bg-accent px-4 text-[14px] font-semibold text-accent-on active:opacity-80"
        >
          <UserSearch className="h-4 w-4" strokeWidth={2.2} aria-hidden />
          Пользователи
        </button>
        <button
          type="button"
          onClick={() => navigate("/modules/parsing/communities")}
          className="inline-flex h-10 shrink-0 items-center gap-1.5 rounded-pill bg-surface-2 px-4 text-[14px] font-medium text-text-primary active:bg-surface-1"
        >
          <Sparkles className="h-4 w-4" strokeWidth={2.2} aria-hidden />
          Каналы и сообщества
        </button>
        <button
          type="button"
          onClick={() => navigate("/modules/parsing/ops")}
          className="inline-flex h-10 shrink-0 items-center gap-1.5 rounded-pill bg-surface-2 px-4 text-[14px] font-medium text-text-primary active:bg-surface-1"
        >
          <Combine className="h-4 w-4" strokeWidth={2.2} aria-hidden />
          Операции
        </button>
      </div>

      <p className="mb-4 text-[13px] text-text-secondary">
        Собранные списки аудитории. Прайминг и другие модули берут отсюда,
        а не парсят повторно.
      </p>

      {isLoading && (
        <div className="flex flex-col gap-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="card h-20 animate-pulse bg-surface-2" />
          ))}
        </div>
      )}
      {isError && (
        <p className="text-[14px] text-status-critical">
          Не удалось загрузить списки.
        </p>
      )}
      {data && data.length === 0 && (
        <EmptyState
          icon={Filter}
          title="Пока нет спарсенных списков"
          hint="Запуск парсера — на экране кампании прайминга или через API /modules/parsing/lists/run/chat-messages."
        />
      )}
      {data && data.length > 0 && (
        <div className="card overflow-hidden p-0">
          {data.map((l, i) => {
            // community_enrich → экран сообществ; все остальные user-парсеры и
            // list_op → экран пользователей. manual_list/upload_csv — тоже
            // наборы юзеров, UserListScreen умеет их рендерить.
            const target: "communities" | "users" | null =
              l.source_kind === "community_enrich"
                ? "communities"
                : [
                    "chat_messages",
                    "chat_members",
                    "channel_commenters",
                    "post_reactors",
                    "list_op",
                    "manual_list",
                    "upload_csv",
                  ].includes(l.source_kind)
                  ? "users"
                  : null;
            const href = target
              ? `/modules/parsing/lists/${l.id}/${target}`
              : undefined;
            return (
              <div
                key={l.id}
                className={`flex items-center gap-4 px-4 py-4 ${i > 0 ? "border-t border-hairline" : ""}`}
              >
                <button
                  type="button"
                  onClick={href ? () => navigate(href) : undefined}
                  className={`flex min-w-0 flex-1 items-center gap-4 text-left ${href ? "active:opacity-70" : "cursor-default"}`}
                  disabled={!href}
                >
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-surface-2 text-text-primary">
                    <Filter className="h-5 w-5" strokeWidth={1.7} aria-hidden />
                  </span>
                  <div className="min-w-0 flex-1">
                    <h3 className="truncate text-[15px] font-semibold leading-tight text-text-primary">
                      {l.name}
                    </h3>
                    <p className="mt-0.5 truncate text-[13px] text-text-tertiary">
                      {SOURCE_LABEL[l.source_kind]}
                      {l.chat_ref ? ` · ${l.chat_ref}` : ""}
                    </p>
                    <p className="mt-0.5 text-[12px] text-text-tertiary">
                      {timeAgo(l.parsed_at ?? l.created_at)}
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    <div className="text-[20px] font-bold tabular-nums text-text-primary">
                      {l.after_filters_count}
                    </div>
                    <div className="text-[11px] uppercase tracking-wider text-text-tertiary">
                      {l.source_kind === "community_enrich" ? "сообществ" : "целей"}
                    </div>
                  </div>
                  {href && (
                    <ChevronRight className="h-4 w-4 shrink-0 text-text-tertiary" strokeWidth={1.8} aria-hidden />
                  )}
                </button>
                {/* Явная кнопка удаления в самой строке (раньше удалить список
                    из UI было невозможно — только через API). */}
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    setConfirmDelete(l);
                  }}
                  aria-label="Удалить список"
                  title="Удалить список"
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-hairline bg-surface-1 text-text-secondary hover:text-status-critical active:bg-surface-2"
                >
                  <Trash2 className="h-4 w-4" strokeWidth={1.8} aria-hidden />
                </button>
              </div>
            );
          })}
        </div>
      )}

      {confirmDelete && (
        <ConfirmDeleteSheet
          name={confirmDelete.name}
          busy={remove.isPending}
          onCancel={() => setConfirmDelete(null)}
          onConfirm={() => remove.mutate(confirmDelete.id)}
        />
      )}
    </div>
  );
}

function ActiveJobRow({
  job,
  isFirst,
  onClick,
}: {
  job: ParsingJob;
  isFirst: boolean;
  onClick: () => void;
}) {
  const paused = job.status === "paused";
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center gap-3 px-4 py-3 text-left active:bg-surface-2 ${isFirst ? "" : "border-t border-hairline"}`}
    >
      {paused ? (
        <Pause className="h-4 w-4 text-status-warning" strokeWidth={2.2} aria-hidden />
      ) : (
        <Loader2 className="h-4 w-4 animate-spin text-status-active" strokeWidth={2.2} aria-hidden />
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate text-[14px] font-medium text-text-primary">
          {job.name || `Прогон ${job.id}`}
        </p>
        <p className="truncate text-[12px] text-text-tertiary">
          {paused ? "Пауза" : "Идёт"} · собрано {job.raw_count}, добавлено{" "}
          {job.inserted_count} · {timeAgo(job.updated_at)}
        </p>
      </div>
      <ChevronRight className="h-4 w-4 shrink-0 text-text-tertiary" strokeWidth={1.8} aria-hidden />
    </button>
  );
}

function ConfirmDeleteSheet({
  name,
  busy,
  onCancel,
  onConfirm,
}: {
  name: string;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center lg:items-center lg:p-6">
      <div onClick={onCancel} className="absolute inset-0 bg-black/60" />
      <div
        role="dialog"
        aria-modal="true"
        className="relative mx-auto w-full max-w-[440px] rounded-t-[28px] border border-hairline bg-bg-elevated p-5 pb-[calc(env(safe-area-inset-bottom)+16px)] lg:rounded-[28px] lg:pb-5"
      >
        <h2 className="text-[18px] font-bold text-text-primary">Удалить список?</h2>
        <p className="mt-1 text-[13px] text-text-tertiary">
          «{name}» будет удалён вместе со всеми собранными целями. Отменить нельзя.
        </p>
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="flex-1 rounded-pill border border-hairline bg-surface-2 px-4 py-3 text-[14px] font-medium text-text-primary active:opacity-80 disabled:opacity-60"
          >
            Отмена
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className="flex-1 rounded-pill bg-status-critical/90 px-4 py-3 text-[14px] font-semibold text-white active:opacity-80 disabled:opacity-60"
          >
            {busy ? "Удаляем…" : "Удалить"}
          </button>
        </div>
      </div>
    </div>
  );
}
