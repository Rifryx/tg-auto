import { useInfiniteQuery } from "@tanstack/react-query";
import { ArrowLeft, Download, X } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { PillGroup } from "./components/PillGroup";
import { primingApi } from "./api";
import type { PrimingExecutionOutcome, PrimingLogRow } from "./types";

/* Экран «Логи» кампании (docs/priming-ui.md §7, prompt 6.4).
   Пилюли-фильтры по outcome, keyset-пагинация, тап по строке → bottom-sheet
   с сырым payload, иконка ⤓ — streaming CSV экспорт (открываем URL). */

const OUTCOME_OPTIONS: {
  key: PrimingExecutionOutcome | "all";
  label: string;
}[] = [
  { key: "all", label: "Все" },
  { key: "primed", label: "Success" },
  { key: "privacy_restricted", label: "Privacy" },
  { key: "flood_wait", label: "Flood" },
  { key: "deleted", label: "Deleted" },
  { key: "not_found", label: "404" },
  { key: "internal_error", label: "Error" },
];

const OUTCOME_TONE: Record<PrimingLogRow["outcome"], string> = {
  primed: "border-status-active",
  already_applied: "border-text-tertiary",
  flood_wait: "border-status-warning",
  privacy_restricted: "border-status-warning",
  deleted: "border-text-tertiary",
  not_found: "border-text-tertiary",
  channel_pinned_error: "border-status-critical",
  skipped_quiet: "border-text-tertiary",
  internal_error: "border-status-critical",
};

const PAGE_SIZE = 50;

export function PrimingCampaignLogs() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const numericId = Number(id);
  const [outcome, setOutcome] = useState<PrimingExecutionOutcome | "all">(
    "all",
  );
  const [openRow, setOpenRow] = useState<PrimingLogRow | null>(null);

  const q = useInfiniteQuery({
    queryKey: ["priming", "campaign", numericId, "logs", outcome],
    queryFn: ({ pageParam }) =>
      primingApi.logs(numericId, {
        outcome: outcome === "all" ? undefined : outcome,
        cursor: pageParam,
        limit: PAGE_SIZE,
      }),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled: Number.isFinite(numericId),
  });

  const rows = q.data?.pages.flatMap((p) => p.items) ?? [];

  const exportUrl = primingApi.exportLogsCsvUrl(numericId, {
    outcome: outcome === "all" ? undefined : outcome,
  });

  return (
    <div className="min-h-full pb-24">
      <ScreenHeader
        title="Логи"
        action={
          <div className="flex items-center gap-2">
            <a
              href={exportUrl}
              className="inline-flex h-9 items-center gap-1.5 rounded-pill bg-surface-2 px-3 text-[13px] text-text-secondary active:text-text-primary"
              aria-label="Экспорт CSV"
            >
              <Download className="h-4 w-4" strokeWidth={2} aria-hidden />
              CSV
            </a>
            <button
              type="button"
              onClick={() => navigate(`/modules/priming/campaigns/${numericId}`)}
              className="inline-flex h-9 items-center gap-1.5 rounded-pill bg-surface-2 px-4 text-[14px] text-text-secondary active:text-text-primary"
            >
              <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
              Назад
            </button>
          </div>
        }
      />

      <div className="mb-3">
        <PillGroup
          value={outcome}
          options={OUTCOME_OPTIONS}
          onChange={(v) => setOutcome(v)}
          fullWidth
        />
      </div>

      {q.isLoading && (
        <div className="card h-16 animate-pulse bg-surface-2" />
      )}

      {!q.isLoading && rows.length === 0 && (
        <div className="card p-6 text-center text-[13px] text-text-tertiary">
          По выбранному фильтру пусто.
        </div>
      )}

      <div className="flex flex-col gap-1.5">
        {rows.map((r) => (
          <button
            type="button"
            key={r.id}
            onClick={() => setOpenRow(r)}
            className={[
              "flex items-center justify-between gap-3 rounded-xl border-l-[3px] bg-surface-1 p-3 text-left active:bg-surface-2",
              OUTCOME_TONE[r.outcome],
            ].join(" ")}
          >
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-[13px] font-medium text-text-primary">
                  {r.outcome}
                </span>
                {r.dry_run && (
                  <span className="rounded-pill bg-surface-2 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-text-secondary">
                    dry
                  </span>
                )}
              </div>
              <div className="mt-0.5 truncate text-[11px] text-text-tertiary">
                {new Date(r.started_at).toLocaleTimeString()} · {r.trigger_action}
                {r.error_code ? ` · ${r.error_code}` : ""}
              </div>
            </div>
            <div className="text-right">
              <div className="text-[13px] tabular-nums text-text-primary">
                {r.latency_ms}ms
              </div>
              <div className="text-[10px] text-text-tertiary">
                #{r.account_id}
              </div>
            </div>
          </button>
        ))}
      </div>

      {q.hasNextPage && (
        <button
          type="button"
          onClick={() => q.fetchNextPage()}
          disabled={q.isFetchingNextPage}
          className="mt-3 h-10 w-full rounded-pill bg-surface-2 text-[13px] text-text-primary disabled:opacity-50"
        >
          {q.isFetchingNextPage ? "Загружаю…" : "Показать ещё"}
        </button>
      )}

      {openRow && (
        <RawPayloadSheet row={openRow} onClose={() => setOpenRow(null)} />
      )}
    </div>
  );
}

function RawPayloadSheet({
  row,
  onClose,
}: {
  row: PrimingLogRow;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-40 flex items-end bg-black/50"
      onClick={onClose}
    >
      <div
        className="w-full rounded-t-3xl border-t border-hairline bg-bg-elevated p-4"
        style={{ paddingBottom: "calc(env(safe-area-inset-bottom) + 16px)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <div className="text-[15px] font-medium text-text-primary">
            #{row.id} · {row.outcome}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-pill bg-surface-2"
            aria-label="Закрыть"
          >
            <X className="h-4 w-4 text-text-secondary" strokeWidth={2} />
          </button>
        </div>
        <pre className="max-h-[60vh] overflow-auto rounded-xl bg-surface-1 p-3 font-mono text-[11px] leading-snug text-text-secondary">
          {JSON.stringify(row, null, 2)}
        </pre>
      </div>
    </div>
  );
}
