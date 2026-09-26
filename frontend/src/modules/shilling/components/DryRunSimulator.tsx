import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, Play, Rocket, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { subscribeStream } from "../../../shared/api";
import { shillingApi } from "../api";

interface StepEvent {
  step_id: number;
  role_name: string;
  text: string;
  scheduled_at_sec: number;
  risk_score: string;
}

interface DoneEvent {
  ok: boolean;
  reason: string | null;
  total_messages: number;
  total_reactions: number;
  duration_sec: number;
  estimated_tokens: number;
}

type Phase = "form" | "running" | "done";

// Грубая оценка $ за токены (усреднённо по DeepSeek/Gemini).
const USD_PER_1K_TOKENS = 0.0002;

export function DryRunSimulator({
  open,
  campaignId,
  onClose,
  onStart,
}: {
  open: boolean;
  campaignId: number;
  onClose: () => void;
  onStart: () => void;
}) {
  const [target, setTarget] = useState("");
  const [phase, setPhase] = useState<Phase>("form");
  const [steps, setSteps] = useState<StepEvent[]>([]);
  const [done, setDone] = useState<DoneEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const unsubRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    return () => unsubRef.current?.();
  }, []);

  const launch = useMutation({
    mutationFn: () => shillingApi.dryRun(campaignId, target.trim()),
    onSuccess: ({ job_id }) => {
      setSteps([]);
      setDone(null);
      setError(null);
      setPhase("running");
      const path = shillingApi.dryRunStreamPath(campaignId, job_id);
      unsubRef.current = subscribeStream(path, (raw) => {
        const ev = raw as Record<string, unknown>;
        if (ev.event === "step") {
          setSteps((prev) => [...prev, ev as unknown as StepEvent]);
        } else if (ev.event === "done") {
          const d = ev as unknown as DoneEvent;
          setDone(d);
          if (!d.ok) setError(d.reason || "Прогон не удался");
          setPhase("done");
          unsubRef.current?.();
        }
      });
    },
    onError: () => setError("Не удалось запустить прогон"),
    meta: { silent: true }, // inline-сообщение в модалке
  });

  if (!open) return null;

  const reset = () => {
    unsubRef.current?.();
    setPhase("form");
    setSteps([]);
    setDone(null);
    setError(null);
  };
  const close = () => {
    reset();
    onClose();
  };

  const worstRisk = steps.reduce<string>((acc, s) => rank(s.risk_score) > rank(acc) ? s.risk_score : acc, "low");
  const validTarget = /^@?[\w\d_]{3,}$/.test(target.trim()) || /t\.me\//i.test(target.trim());

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
              Прогон проиграет сценарий на тестовом чате БЕЗ реальной отправки.
            </p>
            <label className="block">
              <span className="mb-1.5 block px-1 text-[13px] text-text-tertiary">
                Тестовый чат
              </span>
              <input
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                placeholder="@ваш_тест_чат или t.me/…"
                className="h-11 w-full rounded-chip border border-hairline bg-surface-1 px-4 text-[15px] text-text-primary placeholder:text-text-tertiary outline-none focus:border-strong"
              />
            </label>
            {error && <p className="text-[13px] text-status-critical">{error}</p>}
            <button
              onClick={() => launch.mutate()}
              disabled={!validTarget || launch.isPending}
              className="inline-flex h-11 items-center justify-center gap-2 rounded-pill bg-accent text-[15px] font-semibold text-accent-on active:opacity-80 disabled:opacity-40"
            >
              <Play className="h-4 w-4" strokeWidth={2.2} aria-hidden />
              {launch.isPending ? "Запуск…" : "Запустить прогон"}
            </button>
          </div>
        )}

        {(phase === "running" || phase === "done") && (
          <div className="flex flex-col gap-3">
            {/* Таймлайн */}
            <div className="flex max-h-[45vh] flex-col gap-1.5 overflow-y-auto rounded-card bg-bg-base p-3">
              {steps.length === 0 && phase === "running" && (
                <p className="py-4 text-center text-[13px] text-text-tertiary">
                  Проигрываем сценарий…
                </p>
              )}
              {steps.map((s, i) => (
                <div key={i} className="flex items-baseline gap-2 text-[13px]">
                  <span className="shrink-0 text-text-tertiary nums">
                    {fmt(s.scheduled_at_sec)}
                  </span>
                  <span className="shrink-0 font-medium text-text-secondary">{s.role_name}:</span>
                  <span className="min-w-0 flex-1 truncate text-text-primary">{s.text}</span>
                  <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-status-active" strokeWidth={2} aria-hidden />
                </div>
              ))}
            </div>

            {error && <p className="text-[13px] text-status-critical">{error}</p>}

            {/* Сводка */}
            {done && done.ok && (
              <div className="card flex flex-col gap-1.5 p-4 text-[13px]">
                <Row label="Сообщений" value={String(done.total_messages)} />
                <Row label="Реакций" value={String(done.total_reactions)} />
                <Row label="Длительность" value={`${done.duration_sec}с`} />
                <Row
                  label="Расход бюджета"
                  value={`~$${((done.estimated_tokens / 1000) * USD_PER_1K_TOKENS).toFixed(4)}`}
                />
                <Row label="Риск-скор" value={`${riskEmoji(worstRisk)} ${riskLabel(worstRisk)}`} />
              </div>
            )}

            <div className="flex gap-2">
              <button
                onClick={reset}
                className="h-11 flex-1 rounded-pill bg-surface-2 text-[14px] font-medium text-text-primary active:opacity-80"
              >
                Ещё раз
              </button>
              {done?.ok && (
                <button
                  onClick={() => {
                    onStart();
                    close();
                  }}
                  className="inline-flex h-11 flex-1 items-center justify-center gap-1.5 rounded-pill bg-accent text-[14px] font-semibold text-accent-on active:opacity-80"
                >
                  <Rocket className="h-4 w-4" strokeWidth={2.2} aria-hidden />
                  Запустить
                </button>
              )}
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

function fmt(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function rank(level: string): number {
  return { low: 0, medium: 1, high: 2, critical: 3, unknown: 0 }[level] ?? 0;
}
function riskEmoji(level: string): string {
  return { low: "🟢", medium: "🟡", high: "🟠", critical: "🔴", unknown: "⚪" }[level] ?? "⚪";
}
function riskLabel(level: string): string {
  return { low: "низкий", medium: "средний", high: "высокий", critical: "критический", unknown: "неизвестен" }[level] ?? level;
}
