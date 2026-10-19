import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, Play, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { subscribeStream } from "../../../shared/api";
import { ErrorBanner } from "../../../components/ErrorBanner";
import { commentingApi } from "../api";

/* Сухой прогон нейрокомментинга: берём текст тест-поста (или последний пост
   канала) и показываем, какой комментарий сгенерирует каждый аккаунт кампании —
   БЕЗ отправки. По образцу шиллингового DryRunSimulator (та же защита от гонки
   pub/sub на бэкенде). */

interface StepEvent {
  account_id: number;
  account_name: string;
  text: string;
  ok: boolean;
  risk_score: string;
}

interface DoneEvent {
  ok: boolean;
  reason?: string | null;
  total_comments?: number;
  worst_risk?: string;
  estimated_tokens?: number;
}

type Phase = "form" | "running" | "done";

const USD_PER_1K_TOKENS = 0.0002;

export function CommentingDryRun({
  open,
  campaignId,
  onClose,
}: {
  open: boolean;
  campaignId: number;
  onClose: () => void;
}) {
  const [postText, setPostText] = useState("");
  const [channel, setChannel] = useState("");
  const [phase, setPhase] = useState<Phase>("form");
  const [steps, setSteps] = useState<StepEvent[]>([]);
  const [done, setDone] = useState<DoneEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const unsubRef = useRef<(() => void) | null>(null);
  const timeoutRef = useRef<number | null>(null);

  const clearTimer = () => {
    if (timeoutRef.current != null) {
      window.clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  };

  useEffect(() => {
    return () => {
      unsubRef.current?.();
      clearTimer();
    };
  }, []);

  const launch = useMutation({
    mutationFn: () => commentingApi.dryRun(campaignId, postText.trim(), channel.trim()),
    onSuccess: ({ job_id }) => {
      setSteps([]);
      setDone(null);
      setError(null);
      setPhase("running");
      const path = commentingApi.dryRunStreamPath(campaignId, job_id);
      unsubRef.current = subscribeStream(path, (raw) => {
        const ev = raw as Record<string, unknown>;
        if (ev.event === "step") {
          setSteps((prev) => [...prev, ev as unknown as StepEvent]);
        } else if (ev.event === "done") {
          const d = ev as unknown as DoneEvent;
          clearTimer();
          setDone(d);
          if (!d.ok) setError(humanizeReason(d.reason));
          setPhase("done");
          unsubRef.current?.();
        }
      });
      clearTimer();
      timeoutRef.current = window.setTimeout(() => {
        setError((prev) => prev ?? "Прогон не ответил вовремя. Попробуйте ещё раз.");
        setPhase("done");
        unsubRef.current?.();
      }, 90_000);
    },
    onError: () => setError("Не удалось запустить прогон"),
    meta: { silent: true },
  });

  if (!open) return null;

  const reset = () => {
    unsubRef.current?.();
    clearTimer();
    setPhase("form");
    setSteps([]);
    setDone(null);
    setError(null);
  };
  const close = () => {
    reset();
    onClose();
  };

  const canLaunch = (postText.trim().length > 0 || channel.trim().length > 0) && !launch.isPending;
  const worstRisk = steps.reduce<string>(
    (acc, s) => (rank(s.risk_score) > rank(acc) ? s.risk_score : acc),
    "low",
  );

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 sm:items-center">
      <div className="max-h-[90vh] w-full overflow-y-auto rounded-t-card bg-bg-elevated p-5 sm:max-w-lg sm:rounded-card">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-[18px] font-bold text-text-primary">Сухой прогон</h2>
          <button onClick={close} aria-label="Закрыть" className="text-text-tertiary active:text-text-primary">
            <X className="h-5 w-5" strokeWidth={1.8} aria-hidden />
          </button>
        </div>

        {phase === "form" && (
          <div className="flex flex-col gap-4">
            <p className="text-[13px] text-text-tertiary">
              Покажем, какой комментарий сгенерирует каждый аккаунт кампании к посту —
              <b> без отправки</b>.
            </p>
            <label className="block">
              <span className="mb-1.5 block px-1 text-[13px] text-text-tertiary">Текст поста</span>
              <textarea
                value={postText}
                onChange={(e) => setPostText(e.target.value)}
                rows={4}
                placeholder="Вставьте текст поста, на который будут отвечать аккаунты…"
                className="w-full resize-none rounded-chip border border-hairline bg-surface-1 px-4 py-3 text-[15px] text-text-primary placeholder:text-text-tertiary outline-none focus:border-strong"
              />
            </label>
            <label className="block">
              <span className="mb-1.5 block px-1 text-[13px] text-text-tertiary">
                …или канал — возьмём последний пост
              </span>
              <input
                value={channel}
                onChange={(e) => setChannel(e.target.value)}
                placeholder="@канал (если текст выше пуст)"
                className="h-11 w-full rounded-chip border border-hairline bg-surface-1 px-4 text-[15px] text-text-primary placeholder:text-text-tertiary outline-none focus:border-strong"
              />
            </label>
            {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}
            <button
              onClick={() => launch.mutate()}
              disabled={!canLaunch}
              className="inline-flex h-11 items-center justify-center gap-2 rounded-pill bg-accent text-[15px] font-semibold text-accent-on active:opacity-80 disabled:opacity-40"
            >
              <Play className="h-4 w-4" strokeWidth={2.2} aria-hidden />
              {launch.isPending ? "Запуск…" : "Запустить прогон"}
            </button>
          </div>
        )}

        {(phase === "running" || phase === "done") && (
          <div className="flex flex-col gap-3">
            <div className="flex max-h-[45vh] flex-col gap-2 overflow-y-auto rounded-card bg-bg-base p-3">
              {steps.length === 0 && phase === "running" && (
                <p className="py-4 text-center text-[13px] text-text-tertiary">Генерируем комментарии…</p>
              )}
              {steps.map((s, i) => (
                <div key={i} className="rounded-chip border border-hairline bg-surface-1 px-3 py-2">
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <span className="truncate text-[12px] font-medium text-text-secondary">
                      {s.account_name}
                    </span>
                    <span className="shrink-0 text-[11px] text-text-tertiary">
                      {riskEmoji(s.risk_score)} {riskLabel(s.risk_score)}
                    </span>
                  </div>
                  <p className={`text-[13px] ${s.ok ? "text-text-primary" : "text-status-critical"}`}>
                    {s.text}
                  </p>
                </div>
              ))}
            </div>

            {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

            {done && done.ok && (
              <div className="card flex flex-col gap-1.5 p-4 text-[13px]">
                <Row label="Комментариев" value={String(done.total_comments ?? steps.length)} />
                <Row
                  label="Расход бюджета"
                  value={`~$${(((done.estimated_tokens ?? 0) / 1000) * USD_PER_1K_TOKENS).toFixed(4)}`}
                />
                <Row
                  label="Риск-скор"
                  value={`${riskEmoji(done.worst_risk ?? worstRisk)} ${riskLabel(done.worst_risk ?? worstRisk)}`}
                />
              </div>
            )}

            <div className="flex gap-2">
              <button
                onClick={reset}
                className="h-11 flex-1 rounded-pill bg-surface-2 text-[14px] font-medium text-text-primary active:opacity-80"
              >
                Ещё раз
              </button>
              <button
                onClick={close}
                className="inline-flex h-11 flex-1 items-center justify-center gap-1.5 rounded-pill bg-accent text-[14px] font-semibold text-accent-on active:opacity-80"
              >
                <CheckCircle2 className="h-4 w-4" strokeWidth={2.2} aria-hidden />
                Готово
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-text-tertiary">{label}</span>
      <span className="font-medium text-text-primary nums">{value}</span>
    </div>
  );
}

function humanizeReason(reason?: string | null): string {
  const r = reason || "";
  if (r.includes("no accounts")) return "К кампании не привязаны аккаунты.";
  if (r.includes("no post text")) return "Укажите текст поста или канал.";
  if (r.includes("campaign not found")) return "Кампания не найдена.";
  return r || "Прогон не удался";
}

function rank(level: string): number {
  return { low: 0, medium: 1, high: 2, critical: 3, unknown: 0 }[level] ?? 0;
}
function riskEmoji(level: string): string {
  return { low: "🟢", medium: "🟡", high: "🟠", critical: "🔴", unknown: "⚪" }[level] ?? "⚪";
}
function riskLabel(level: string): string {
  return (
    { low: "низкий", medium: "средний", high: "высокий", critical: "критический", unknown: "неизвестен" }[
      level
    ] ?? level
  );
}
