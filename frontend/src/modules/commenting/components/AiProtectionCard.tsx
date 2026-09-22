import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, ShieldCheck } from "lucide-react";
import { aiProtectionApi } from "../api";
import type { AiProtectionFeature } from "../types";

/* Read-only плашка «ИИ Защита аккаунтов активна» (§ Этап 5).
 *
 * Заменяет paywall'ную заглушку конкурента. Показывает 4 подсистемы
 * защиты (все всегда «active», daemon'ы крутятся cron'ом воркера)
 * и агрегат по риск-бакетам аккаунтов. Данные тянутся из
 * /modules/commenting/ai-protection/status. */

export function AiProtectionCard() {
  const { data, isLoading } = useQuery({
    queryKey: ["ai-protection-status"],
    queryFn: aiProtectionApi.status,
    refetchInterval: 60_000,
  });

  return (
    <section className="mb-7">
      <div className="rounded-card border border-status-active bg-surface-1 p-4">
        <div className="mb-3 flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-status-active/15 text-status-active">
            <ShieldCheck className="h-5 w-5" strokeWidth={2} aria-hidden />
          </div>
          <div className="min-w-0">
            <p className="text-[15px] font-semibold text-text-primary">
              ИИ Защита аккаунтов
            </p>
            <p className="text-[12px] text-text-tertiary">
              Работает в фоне на всех аккаунтах — не требует включения.
            </p>
          </div>
          <span className="ml-auto rounded-pill bg-status-active/15 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-status-active">
            активна
          </span>
        </div>

        <div className="mb-3 grid grid-cols-2 gap-2">
          {(data?.features ?? PLACEHOLDER_FEATURES).map((f) => (
            <FeatureChip key={f.key} feature={f} />
          ))}
        </div>

        {data && data.total_accounts > 0 && (
          <div className="rounded-chip border border-hairline bg-surface-2 px-3 py-2">
            <p className="mb-1.5 text-[12px] text-text-tertiary">
              Аккаунтов под наблюдением: {data.total_accounts}
            </p>
            <div className="flex flex-wrap gap-1.5 text-[11px]">
              <RiskChip label="low" count={data.accounts_by_risk.low} tone="ok" />
              <RiskChip label="medium" count={data.accounts_by_risk.medium} tone="warn" />
              <RiskChip label="high" count={data.accounts_by_risk.high} tone="risk" />
              <RiskChip label="critical" count={data.accounts_by_risk.critical} tone="risk" />
              <RiskChip
                label="не считался"
                count={data.accounts_by_risk.unknown}
                tone="muted"
              />
            </div>
          </div>
        )}
        {isLoading && !data && (
          <p className="text-[12px] text-text-tertiary">Загрузка статуса…</p>
        )}
      </div>
    </section>
  );
}

function FeatureChip({ feature }: { feature: AiProtectionFeature }) {
  return (
    <div className="flex items-start gap-2 rounded-chip border border-hairline bg-surface-1 px-3 py-2">
      <CheckCircle2
        className="mt-0.5 h-4 w-4 shrink-0 text-status-active"
        strokeWidth={2}
        aria-hidden
      />
      <div className="min-w-0">
        <p className="text-[13px] text-text-primary">{feature.label}</p>
        <p className="text-[11px] text-text-tertiary">{feature.description}</p>
      </div>
    </div>
  );
}

function RiskChip({
  label,
  count,
  tone,
}: {
  label: string;
  count: number;
  tone: "ok" | "warn" | "risk" | "muted";
}) {
  const cls = {
    ok: "bg-status-active/15 text-status-active",
    warn: "bg-status-warning/15 text-status-warning",
    risk: "bg-status-critical/15 text-status-critical",
    muted: "bg-surface-1 text-text-tertiary",
  }[tone];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-pill px-2 py-0.5 font-semibold ${cls}`}
    >
      {label}: {count}
    </span>
  );
}

/* Фолбэк на случай, если запрос статуса не успел прийти —
   даём тот же набор фич, что и backend, но status='active' bydefault. */
const PLACEHOLDER_FEATURES: AiProtectionFeature[] = [
  {
    key: "behavior_analysis",
    label: "ИИ анализ поведения",
    description: "Предиктор пересчитывает риск раз в 15 минут.",
    status: "active",
  },
  {
    key: "human_mimicry",
    label: "Имитация человека",
    description: "Warming maintenance каждые 5 минут.",
    status: "active",
  },
  {
    key: "ban_shield",
    label: "Защита от банов",
    description: "Автопилот снимает нагрузку с рискующих аккаунтов.",
    status: "active",
  },
  {
    key: "adaptive_delays",
    label: "Адаптивные задержки",
    description: "Delay-пресет + автопауза при FloodWait.",
    status: "active",
  },
];
