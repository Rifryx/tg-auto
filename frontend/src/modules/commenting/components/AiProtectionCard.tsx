import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, ShieldCheck } from "lucide-react";
import { aiProtectionApi } from "../api";
import type { AiProtectionFeature } from "../types";

/* Read-only плашка «ИИ Защита аккаунтов активна» (§ Этап 5).
 *
 * Заменяет paywall'ную заглушку конкурента. Показывает 4 подсистемы
 * защиты (все всегда «active», daemon'ы крутятся cron'ом воркера).
 * Данные тянутся из /modules/commenting/ai-protection/status. */

export function AiProtectionCard() {
  const { data } = useQuery({
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

        <div className="grid grid-cols-2 gap-2">
          {(data?.features ?? PLACEHOLDER_FEATURES).map((f) => (
            <FeatureChip key={f.key} feature={f} />
          ))}
        </div>
      </div>
    </section>
  );
}

/* Короткие, человекочитаемые описания для плиток. Backend присылает
   более подробный текст с внутренними id задач (напр.
   «(задача health.predict_ban_risk_batch)») — такие длинные неразрывные
   токены распирают карточку. В UI показываем лаконичную версию по ключу,
   а на незнакомый ключ аккуратно укорачиваем backend-текст. */
const SHORT_DESC: Record<string, string> = {
  behavior_analysis: "Anti-Ban Predictor пересчитывает риск каждые 15 минут.",
  human_mimicry: "Warming-поддержка каждые 5 минут имитирует живое поведение.",
  ban_shield: "Health-монитор уводит рискующие аккаунты с нагрузки.",
  adaptive_delays: "Адаптивные задержки постинга и автопауза при FloodWait.",
};

/* Обрезает служебный хвост «(задача …)» и внутренние id из backend-текста. */
function tidyDescription(key: string, raw: string): string {
  if (SHORT_DESC[key]) return SHORT_DESC[key];
  return raw.replace(/\s*\(задача[^)]*\)\.?/gi, ".").replace(/\s{2,}/g, " ").trim();
}

function FeatureChip({ feature }: { feature: AiProtectionFeature }) {
  return (
    <div className="flex min-w-0 items-start gap-2 rounded-chip border border-hairline bg-surface-1 px-3 py-2.5">
      <CheckCircle2
        className="mt-0.5 h-4 w-4 shrink-0 text-status-active"
        strokeWidth={2}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-medium text-text-primary [overflow-wrap:anywhere] hyphens-auto">
          {feature.label}
        </p>
        <p className="mt-0.5 text-[11px] leading-snug text-text-tertiary [overflow-wrap:anywhere] hyphens-auto">
          {tidyDescription(feature.key, feature.description)}
        </p>
      </div>
    </div>
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
