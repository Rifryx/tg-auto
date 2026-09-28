import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Pause, Play } from "lucide-react";
import { useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { primingApi } from "./api";
import { StatusDot } from "./components/StatusDot";
import type { PrimingLiveAccountRow } from "./types";

/* Экран «Ход» кампании прайминга (docs/priming-ui.md §6, prompt 6.3).
   Hero-KPI со спарклайном 24 ч, ряд мини-KPI, список аккаунтов и
   тумблер dry-run в шапке (доступен только вне running). */

const REFRESH_MS = 5_000;

export function PrimingCampaignRun() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const numericId = Number(id);

  const campaignQuery = useQuery({
    queryKey: ["priming", "campaign", numericId],
    queryFn: () => primingApi.get(numericId),
    enabled: Number.isFinite(numericId),
  });
  const liveQuery = useQuery({
    queryKey: ["priming", "campaign", numericId, "live"],
    queryFn: () => primingApi.live(numericId),
    enabled: Number.isFinite(numericId),
    refetchInterval: REFRESH_MS,
  });
  const forecastQuery = useQuery({
    queryKey: ["priming", "campaign", numericId, "forecast"],
    queryFn: () => primingApi.forecast(numericId),
    enabled: Number.isFinite(numericId),
    refetchInterval: REFRESH_MS * 4,
  });
  const forecast = forecastQuery.data;

  const campaign = campaignQuery.data;
  const live = liveQuery.data;

  const totalAttempts = useMemo(
    () =>
      live
        ? Object.values(live.counters).reduce((a, b) => a + b, 0)
        : 0,
    [live],
  );
  const primed = live?.counters.primed ?? 0;
  const successRate = totalAttempts > 0 ? primed / totalAttempts : 0;

  const setDryRun = useMutation({
    mutationFn: (value: boolean) =>
      primingApi.update(numericId, { dry_run: value }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["priming", "campaign", numericId] });
    },
  });

  const pause = useMutation({
    mutationFn: () => primingApi.pause(numericId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["priming", "campaign", numericId] });
    },
  });
  const resume = useMutation({
    mutationFn: () => primingApi.resume(numericId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["priming", "campaign", numericId] });
    },
  });

  const dryRunEditable =
    campaign && ["draft", "paused", "stopped"].includes(campaign.status);

  return (
    <div className="min-h-full pb-24">
      <ScreenHeader
        title={campaign?.name ?? "Кампания"}
        action={
          <button
            type="button"
            onClick={() => navigate(`/modules/priming/campaigns/${numericId}`)}
            className="inline-flex h-9 items-center gap-1.5 rounded-pill bg-surface-2 px-4 text-[14px] text-text-secondary active:text-text-primary"
          >
            <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
            К кампании
          </button>
        }
      />

      {(campaignQuery.isLoading || liveQuery.isLoading) && (
        <div className="card h-40 animate-pulse bg-surface-2" />
      )}

      {campaign && live && (
        <div className="flex flex-col gap-3">
          {/* Шапка со статусом + dry-run */}
          <div className="card flex items-center justify-between gap-3 p-4">
            <div className="flex items-center gap-2">
              <StatusDot status={campaign.status} />
              <span className="text-[15px] font-medium text-text-primary">
                {campaign.status}
              </span>
              {campaign.dry_run && (
                <span className="rounded-pill bg-surface-2 px-2 py-0.5 text-[10px] uppercase tracking-wider text-text-secondary">
                  dry-run
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {campaign.status === "running" && (
                <button
                  type="button"
                  onClick={() => pause.mutate()}
                  disabled={pause.isPending}
                  className="inline-flex h-9 items-center gap-1.5 rounded-pill bg-surface-2 px-3 text-[13px] text-text-primary"
                >
                  <Pause className="h-3.5 w-3.5" strokeWidth={2.5} aria-hidden />
                  Пауза
                </button>
              )}
              {(campaign.status === "paused" || campaign.status === "stopped") && (
                <button
                  type="button"
                  onClick={() => resume.mutate()}
                  disabled={resume.isPending}
                  className="inline-flex h-9 items-center gap-1.5 rounded-pill bg-accent px-3 text-[13px] font-semibold text-accent-on"
                >
                  <Play className="h-3.5 w-3.5" strokeWidth={2.5} aria-hidden />
                  Возобновить
                </button>
              )}
            </div>
          </div>

          {/* Hero KPI */}
          <div className="card p-4">
            <div className="flex items-baseline justify-between">
              <div>
                <div className="text-[11px] uppercase tracking-wider text-text-tertiary">
                  Успешных праймов
                </div>
                <div className="mt-1 flex items-baseline gap-2">
                  <span className="text-[32px] font-semibold tabular-nums text-text-primary">
                    {primed}
                  </span>
                  <span className="text-[13px] text-text-tertiary">
                    из {totalAttempts}
                  </span>
                </div>
              </div>
              <div className="text-right">
                <div className="text-[11px] uppercase tracking-wider text-text-tertiary">
                  Success rate
                </div>
                <div className="mt-1 text-[20px] font-semibold tabular-nums text-text-primary">
                  {(successRate * 100).toFixed(1)}%
                </div>
              </div>
            </div>
            <div className="mt-4">
              <Sparkline values={live.sparkline_24h} />
              <div className="mt-1 flex justify-between text-[10px] uppercase tracking-wider text-text-tertiary">
                <span>−24 ч</span>
                <span>сейчас</span>
              </div>
            </div>
          </div>

          {/* Прогноз «Что произойдёт за час» */}
          {forecast && (
            <div className="card p-4">
              <div className="text-[11px] uppercase tracking-wider text-text-tertiary">
                Прогноз на ближайший час
              </div>
              <div className="mt-2 grid grid-cols-3 gap-3">
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-text-tertiary">
                    Ожидается primed
                  </div>
                  <div className="mt-1 text-[20px] font-semibold tabular-nums text-text-primary">
                    ≈ {forecast.expected_primes_per_hour}
                  </div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-text-tertiary">
                    Ожидается flood
                  </div>
                  <div className="mt-1 text-[20px] font-semibold tabular-nums text-status-warning">
                    ≈ {forecast.expected_flood_per_hour}
                  </div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-text-tertiary">
                    Старт через
                  </div>
                  <div className="mt-1 text-[20px] font-semibold tabular-nums text-text-primary">
                    {forecast.best_start_after === 0
                      ? "сейчас"
                      : `${Math.ceil(forecast.best_start_after / 60)}м`}
                  </div>
                </div>
              </div>
              <p className="mt-2 text-[11px] text-text-tertiary">
                На основе {forecast.sample_size} последних попыток и текущего
                профиля прогрева.
              </p>
            </div>
          )}

          {/* A/B breakdown — только если тест включён */}
          {live.ab_split_enabled && live.ab_breakdown && (
            <div className="card p-4">
              <div className="mb-3 text-[11px] uppercase tracking-wider text-text-tertiary">
                A/B test · доля A ~ {Math.round(live.ab_split_ratio * 100)}%
              </div>
              <div className="grid grid-cols-2 gap-3">
                <ABColumn label="A" value={live.ab_breakdown.a} />
                <ABColumn label="B" value={live.ab_breakdown.b} />
              </div>
            </div>
          )}

          {/* Мини-KPI */}
          <div className="-mx-4 overflow-x-auto px-4 pb-1">
            <div className="flex gap-2">
              <MiniKpi label="Privacy" value={live.counters.privacy_restricted ?? 0} tone="warning" />
              <MiniKpi label="Flood-wait" value={live.counters.flood_wait ?? 0} tone="warning" />
              <MiniKpi label="Deleted" value={live.counters.deleted ?? 0} tone="muted" />
              <MiniKpi label="Not found" value={live.counters.not_found ?? 0} tone="muted" />
              <MiniKpi
                label="Карантин"
                value={live.accounts.filter((a) => a.state === "quarantined").length}
                tone="critical"
              />
            </div>
          </div>

          {/* Dry-run тумблер */}
          <div className="card p-4">
            <label className="flex cursor-pointer items-center justify-between gap-3">
              <div>
                <div className="text-[14px] font-medium text-text-primary">
                  Тестовый прогон (dry-run)
                </div>
                <p className="mt-0.5 text-[12px] text-text-tertiary">
                  Симуляция исходов без реальных Push. Доступен только в
                  draft / paused / stopped.
                </p>
              </div>
              <input
                type="checkbox"
                checked={campaign.dry_run}
                disabled={!dryRunEditable || setDryRun.isPending}
                onChange={(e) => setDryRun.mutate(e.target.checked)}
                className="h-5 w-5 accent-text-primary disabled:opacity-40"
              />
            </label>
          </div>

          {/* Список аккаунтов */}
          <div className="card p-2">
            <div className="px-2 pt-2 text-[11px] uppercase tracking-wider text-text-tertiary">
              Аккаунты · {live.accounts.length}
            </div>
            <div className="mt-2 flex flex-col gap-1">
              {live.accounts.map((a) => (
                <AccountRunRow key={a.id} row={a} />
              ))}
              {live.accounts.length === 0 && (
                <p className="p-3 text-[13px] text-text-tertiary">
                  Аккаунтов пока нет.
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────

function Sparkline({ values }: { values: number[] }) {
  const w = 320;
  const h = 56;
  const max = Math.max(1, ...values);
  const step = values.length > 1 ? w / (values.length - 1) : 0;
  const points = values.map((v, i) => {
    const x = i * step;
    const y = h - (v / max) * (h - 6) - 3;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const linePath = `M ${points.join(" L ")}`;
  const areaPath = `${linePath} L ${w},${h} L 0,${h} Z`;
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      className="h-14 w-full"
      aria-hidden
    >
      <path
        d={areaPath}
        fill="var(--status-active)"
        opacity="0.08"
      />
      <path
        d={linePath}
        fill="none"
        stroke="var(--status-active)"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function MiniKpi({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "muted" | "warning" | "critical";
}) {
  const toneStyle: Record<typeof tone, string> = {
    muted: "text-text-secondary",
    warning: "text-status-warning",
    critical: "text-status-critical",
  };
  return (
    <div className="shrink-0 rounded-2xl border border-hairline bg-surface-1 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-text-tertiary">
        {label}
      </div>
      <div className={`mt-1 text-[16px] font-semibold tabular-nums ${toneStyle[tone]}`}>
        {value}
      </div>
    </div>
  );
}

function ABColumn({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2xl border border-hairline bg-surface-1 p-3">
      <div className="text-[10px] uppercase tracking-wider text-text-tertiary">
        Bucket {label}
      </div>
      <div className="mt-1 text-[20px] font-semibold tabular-nums text-text-primary">
        {value}
      </div>
      <div className="text-[10px] text-text-tertiary">primed</div>
    </div>
  );
}

function AccountRunRow({ row }: { row: PrimingLiveAccountRow }) {
  const stateLabel: Record<PrimingLiveAccountRow["state"], string> = {
    idle: "ожидает",
    working: "работает",
    cooldown: "cooldown",
    quarantined: "карантин",
    disabled: "выкл.",
  };
  const dot: Record<PrimingLiveAccountRow["state"], string> = {
    idle: "bg-text-tertiary",
    working: "bg-status-active",
    cooldown: "bg-status-warning",
    quarantined: "bg-status-critical",
    disabled: "bg-text-tertiary",
  };
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl p-2.5">
      <div className="flex items-center gap-2 min-w-0">
        <span
          className={`h-2 w-2 shrink-0 rounded-full ${dot[row.state]}`}
          aria-hidden
        />
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="truncate text-[14px] text-text-primary">
              #{row.account_id}
            </span>
            {row.ab_bucket && (
              <span className="rounded-pill bg-surface-2 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-text-secondary">
                {row.ab_bucket}
              </span>
            )}
          </div>
          <div className="text-[11px] text-text-tertiary">
            {stateLabel[row.state]}
            {row.flood_waits_consecutive > 0 && (
              <>
                {" · "}
                <span className="text-status-warning">
                  flood ×{row.flood_waits_consecutive}
                </span>
              </>
            )}
          </div>
        </div>
      </div>
      <div className="text-right">
        <div className="text-[14px] tabular-nums text-text-primary">
          {row.primes_today}
        </div>
        <div className="text-[10px] uppercase tracking-wider text-text-tertiary">
          сегодня
        </div>
      </div>
    </div>
  );
}
