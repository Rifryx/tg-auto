import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, XCircle, X } from "lucide-react";
import { api } from "../../../shared/api";
import type { BulkJobDetail, BulkJobRead, BulkJobStatus } from "../../../shared/types";
import { CapsuleButton } from "./ui";

/* Шторка с живым прогрессом конкретного bulk-задания (apply_profile_pool,
   publish_story, generate_and_apply_profile, assign_proxy, logout_other_sessions
   и т.п.). Раньше после запуска показывался только тост «задача запущена», и
   результат по каждому аккаунту пользователь нигде не видел — приходилось
   верить. Теперь после enqueue мы открываем это окно и поллим /bulk-jobs/{id},
   пока статус не станет финальным. */

const ACTION_LABEL: Record<string, string> = {
  apply_profile_pool: "Профиль из пула",
  generate_and_apply_profile: "Профиль ИИ",
  publish_story: "Публикация Stories",
  assign_proxy: "Раздача прокси",
  logout_other_sessions: "Сброс сессий",
};

const STATUS_LABEL: Record<BulkJobStatus, { label: string; cls: string }> = {
  queued: { label: "В очереди", cls: "text-text-tertiary" },
  running: { label: "Выполняется", cls: "text-status-active" },
  done: { label: "Готово", cls: "text-status-active" },
  failed: { label: "Ошибки", cls: "text-status-critical" },
  cancelled: { label: "Отменено", cls: "text-text-secondary" },
};

const TERMINAL: BulkJobStatus[] = ["done", "failed", "cancelled"];

export function BulkJobsSheet({ jobId, onClose }: { jobId: number; onClose: () => void }) {
  const qc = useQueryClient();
  const detail = useQuery({
    queryKey: ["bulk-job", jobId],
    queryFn: () => api.get<BulkJobDetail>(`/bulk-jobs/${jobId}`),
    refetchInterval: (q) =>
      q.state.data && TERMINAL.includes(q.state.data.job.status) ? false : 1500,
  });

  const cancel = useMutation({
    mutationFn: () => api.post<BulkJobRead>(`/bulk-jobs/${jobId}/cancel`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bulk-job", jobId] }),
  });

  const data = detail.data;
  const job = data?.job;
  const items = data?.items ?? [];
  const status = job?.status ?? "queued";
  const meta = STATUS_LABEL[status] ?? STATUS_LABEL.queued;
  const total = job?.total_count ?? 0;
  const done = job?.done_count ?? 0;
  const failed = job?.failed_count ?? 0;
  const skipped = job?.skipped_count ?? 0;
  const pct = total > 0 ? Math.round(((done + failed + skipped) / total) * 100) : 0;

  const actionLabel = job
    ? ACTION_LABEL[job.action_type] ?? job.action_type
    : "Задание";

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center px-3 pb-4 pt-4 lg:items-center lg:px-4 bg-[color-mix(in_srgb,var(--bg-base)_72%,transparent)]"
      onClick={onClose}
    >
      <div
        className="flex max-h-[calc(100dvh-32px)] w-full max-w-[480px] flex-col rounded-card border border-strong bg-bg-elevated"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-hairline px-5 pb-3 pt-5">
          <div className="min-w-0">
            <h3 className="truncate text-[17px] font-semibold text-text-primary">
              {actionLabel}
            </h3>
            <p className={`mt-0.5 text-[13px] ${meta.cls}`}>
              {meta.label} · {done + failed + skipped}/{total}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Закрыть"
            className="shrink-0 inline-flex h-8 w-8 items-center justify-center rounded-full bg-surface-2 text-text-secondary active:text-text-primary"
          >
            <X className="h-4 w-4" strokeWidth={1.8} aria-hidden />
          </button>
        </div>

        <div className="border-b border-hairline px-5 py-3">
          <div className="mb-2 h-2 w-full overflow-hidden rounded-full bg-surface-2">
            <div
              className="h-full bg-status-active transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
          <div className="flex items-center gap-3 text-[12px] text-text-tertiary">
            <span className="inline-flex items-center gap-1 text-status-active">
              <CheckCircle2 className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
              <span className="nums">{done}</span>
            </span>
            {failed > 0 && (
              <span className="inline-flex items-center gap-1 text-status-critical">
                <XCircle className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
                <span className="nums">{failed}</span>
              </span>
            )}
            {skipped > 0 && (
              <span className="text-text-tertiary nums">пропущено {skipped}</span>
            )}
            {status === "running" && (
              <Loader2 className="ml-auto h-3.5 w-3.5 animate-spin" strokeWidth={2} aria-hidden />
            )}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-3 [scrollbar-width:thin]">
          {items.length === 0 ? (
            <p className="py-6 text-center text-[12px] text-text-tertiary">
              Ждём первые результаты…
            </p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {items.map((it) => (
                <li
                  key={it.id}
                  className="flex items-center gap-2 rounded-chip border border-hairline bg-surface-1 px-3 py-2"
                >
                  <span
                    className={`inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${
                      it.status === "done"
                        ? "text-status-active"
                        : it.status === "failed"
                          ? "text-status-critical"
                          : it.status === "skipped"
                            ? "text-text-tertiary"
                            : "text-text-secondary"
                    }`}
                    aria-hidden
                  >
                    {it.status === "done" ? (
                      <CheckCircle2 className="h-4 w-4" strokeWidth={2} />
                    ) : it.status === "failed" ? (
                      <XCircle className="h-4 w-4" strokeWidth={2} />
                    ) : (
                      <Loader2
                        className={`h-3.5 w-3.5 ${
                          it.status === "running" ? "animate-spin" : ""
                        }`}
                        strokeWidth={2}
                      />
                    )}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] text-text-primary">
                      Аккаунт #{it.account_id}
                    </p>
                    {it.error && (
                      <p className="truncate text-[11px] text-status-critical">
                        {it.error}
                      </p>
                    )}
                    {!it.error && it.result && (
                      <p className="truncate text-[11px] text-text-tertiary">
                        {renderResult(it.result)}
                      </p>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div
          className="flex flex-col gap-2 border-t border-hairline px-5 pt-3"
          style={{ paddingBottom: "calc(env(safe-area-inset-bottom) + 14px)" }}
        >
          {!TERMINAL.includes(status) && (
            <CapsuleButton
              variant="secondary"
              disabled={cancel.isPending}
              onClick={() => cancel.mutate()}
            >
              {cancel.isPending ? "Отменяем…" : "Остановить задание"}
            </CapsuleButton>
          )}
          <CapsuleButton onClick={onClose}>Закрыть</CapsuleButton>
        </div>
      </div>
    </div>
  );
}

function renderResult(r: Record<string, unknown>): string {
  // Коротко показываем самое интересное; полный JSON — в логах.
  const parts: string[] = [];
  if (typeof r.message_id === "number") parts.push(`msg #${r.message_id}`);
  if (typeof r.applied === "number") parts.push(`применено: ${r.applied}`);
  if (typeof r.proxy_id === "number") parts.push(`прокси #${r.proxy_id}`);
  if (typeof r.sessions_logged_out === "number")
    parts.push(`сессий выкинуто: ${r.sessions_logged_out}`);
  return parts.join(" · ") || "ок";
}
