import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CheckCircle2,
  Loader2,
  Pause,
  Play,
  Square,
  XCircle,
} from "lucide-react";
import { useEffect, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { parsingApi } from "./api";
import type { ParsingJobStatus } from "./types";

/* Окно живого прогресса парсинга: лог в реальном времени, счётчики и управление
   (пауза/продолжить/остановить). Поллит GET /modules/parsing/jobs/{id}. */

const STATUS_META: Record<
  ParsingJobStatus,
  { label: string; cls: string }
> = {
  pending: { label: "Ожидает", cls: "text-text-tertiary" },
  running: { label: "Выполняется", cls: "text-status-active" },
  paused: { label: "На паузе", cls: "text-status-warning" },
  done: { label: "Готово", cls: "text-status-active" },
  failed: { label: "Ошибка", cls: "text-status-critical" },
  stopped: { label: "Остановлено", cls: "text-text-secondary" },
};

const TERMINAL = new Set<ParsingJobStatus>(["done", "failed", "stopped"]);

export function ParsingRunScreen() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { jobId } = useParams();
  const id = Number(jobId);

  const job = useQuery({
    queryKey: ["parsing-job", id],
    queryFn: () => parsingApi.job(id),
    // Поллим, пока задача не завершилась.
    refetchInterval: (q) =>
      q.state.data && TERMINAL.has(q.state.data.status) ? false : 1500,
    enabled: Number.isFinite(id),
  });

  const control = useMutation({
    mutationFn: (action: "pause" | "resume" | "stop") =>
      parsingApi.controlJob(id, action),
    onSuccess: (data) => qc.setQueryData(["parsing-job", id], data),
  });

  const data = job.data;
  const status = data?.status ?? "pending";
  const meta = STATUS_META[status];
  const active = status === "running" || status === "paused" || status === "pending";

  // Автоскролл лога вниз при новых строках.
  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [data?.log?.length]);

  return (
    <div className="min-h-full">
      <ScreenHeader
        title="Парсинг"
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

      <div className="flex flex-col gap-4">
        {/* Статус + счётчики */}
        <div className="card p-5">
          <div className="mb-3 flex items-center gap-2">
            {status === "running" || status === "pending" ? (
              <Loader2 className="h-5 w-5 animate-spin text-status-active" strokeWidth={2} aria-hidden />
            ) : status === "done" ? (
              <CheckCircle2 className="h-5 w-5 text-status-active" strokeWidth={2} aria-hidden />
            ) : status === "failed" ? (
              <XCircle className="h-5 w-5 text-status-critical" strokeWidth={2} aria-hidden />
            ) : (
              <Pause className="h-5 w-5 text-status-warning" strokeWidth={2} aria-hidden />
            )}
            <span className={`text-[16px] font-semibold ${meta.cls}`}>{meta.label}</span>
            {data?.name && (
              <span className="ml-auto truncate text-[13px] text-text-tertiary">{data.name}</span>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Counter label="Собрано" value={data?.raw_count ?? 0} />
            <Counter label="Добавлено" value={data?.inserted_count ?? 0} />
          </div>

          {data?.error && (
            <p className="mt-3 break-all rounded-xl border border-status-critical/40 bg-status-critical/5 p-2.5 font-mono text-[12px] text-status-critical">
              {data.error}
            </p>
          )}

          {status === "done" && data?.list_id != null && (
            <button
              type="button"
              onClick={() => navigate("/modules/parsing")}
              className="mt-3 inline-flex h-10 w-full items-center justify-center rounded-pill bg-accent text-[14px] font-semibold text-accent-on active:opacity-80"
            >
              К спискам
            </button>
          )}
        </div>

        {/* Управление */}
        {active && (
          <div className="card flex gap-2 p-4">
            {status === "paused" ? (
              <button
                type="button"
                disabled={control.isPending}
                onClick={() => control.mutate("resume")}
                className="inline-flex h-11 flex-1 items-center justify-center gap-2 rounded-pill bg-status-active/15 text-[14px] font-semibold text-status-active active:opacity-80 disabled:opacity-50"
              >
                <Play className="h-4 w-4" strokeWidth={2.2} aria-hidden />
                Продолжить
              </button>
            ) : (
              <button
                type="button"
                disabled={control.isPending}
                onClick={() => control.mutate("pause")}
                className="inline-flex h-11 flex-1 items-center justify-center gap-2 rounded-pill bg-surface-2 text-[14px] font-semibold text-text-primary active:opacity-80 disabled:opacity-50"
              >
                <Pause className="h-4 w-4" strokeWidth={2.2} aria-hidden />
                Пауза
              </button>
            )}
            <button
              type="button"
              disabled={control.isPending}
              onClick={() => control.mutate("stop")}
              className="inline-flex h-11 flex-1 items-center justify-center gap-2 rounded-pill bg-status-critical/15 text-[14px] font-semibold text-status-critical active:opacity-80 disabled:opacity-50"
            >
              <Square className="h-4 w-4" strokeWidth={2.2} aria-hidden />
              Остановить
            </button>
          </div>
        )}

        {/* Лог в реальном времени */}
        <div className="card p-4">
          <div className="mb-2 text-[13px] font-medium uppercase tracking-wider text-text-secondary">
            Лог
          </div>
          <div
            ref={logRef}
            className="max-h-80 overflow-y-auto rounded-xl bg-surface-1 p-3 font-mono text-[12px] leading-relaxed text-text-secondary"
          >
            {(data?.log ?? []).length === 0 ? (
              <p className="text-text-tertiary">Ожидаем первые события…</p>
            ) : (
              (data?.log ?? []).map((line, i) => (
                <div key={i} className="flex gap-2">
                  <span className="shrink-0 text-text-tertiary">
                    {new Date(line.ts).toLocaleTimeString("ru-RU", {
                      hour: "2-digit",
                      minute: "2-digit",
                      second: "2-digit",
                    })}
                  </span>
                  <span className="min-w-0 break-words">{line.msg}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Counter({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-hairline bg-surface-1 p-3">
      <p className="nums text-[24px] font-bold leading-none text-text-primary">{value}</p>
      <p className="mt-1 text-[12px] text-text-tertiary">{label}</p>
    </div>
  );
}
