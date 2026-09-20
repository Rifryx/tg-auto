import { useQuery } from "@tanstack/react-query";
import { ShieldAlert, ShieldCheck, TrendingDown, TrendingUp } from "lucide-react";
import {
  banRiskApi,
  factorLabel,
  RISK_LEVEL_LABEL,
  riskDotClass,
  riskLevelBgClass,
} from "../../../shared/banRisk";
import { timeAgo } from "../../../shared/format";
import { Section } from "../../../modules/commenting/components/ui";

/* Виджет ban-risk для карточки аккаунта (этап 13, UI для этапа 11).
 *
 * Показывает: risk_score, risk_level, дельту к предыдущему значению, топ-3
 * фактора с их вкладом в risk. Данные обновляются каждые 30 секунд. */

export function BanRiskCard({ accountId }: { accountId: number }) {
  const { data, isLoading } = useQuery({
    queryKey: ["ban-risk", accountId],
    queryFn: () => banRiskApi.get(accountId),
    refetchInterval: 30_000,
  });

  if (isLoading || !data) return null;

  const percent = Math.round(data.risk_score * 100);
  const prevPercent =
    data.previous_risk_score != null
      ? Math.round(data.previous_risk_score * 100)
      : null;
  const delta = prevPercent != null ? percent - prevPercent : null;

  const topFactors = [...data.contributions]
    .filter((c) => c.contribution > 0)
    .sort((a, b) => b.contribution - a.contribution)
    .slice(0, 3);

  return (
    <Section title="Риск бана">
      <div className="card p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            {data.risk_level === "critical" || data.risk_level === "high" ? (
              <ShieldAlert className="h-6 w-6 text-danger" strokeWidth={1.8} aria-hidden />
            ) : (
              <ShieldCheck className="h-6 w-6 text-success" strokeWidth={1.8} aria-hidden />
            )}
            <div>
              <div className="flex items-baseline gap-2">
                <span className="text-[24px] font-semibold tabular-nums text-text-primary">
                  {percent}
                </span>
                <span className="text-[13px] text-text-tertiary">/ 100</span>
              </div>
              <div
                className={`inline-flex items-center gap-1.5 rounded-pill px-2 py-0.5 text-[11px] font-medium ${riskLevelBgClass(
                  data.risk_level,
                )}`}
              >
                <span className={`inline-block h-1.5 w-1.5 rounded-full ${riskDotClass(data.risk_level)}`} />
                {RISK_LEVEL_LABEL[data.risk_level]}
              </div>
            </div>
          </div>
          {delta != null && delta !== 0 && (
            <div className="flex items-center gap-1 text-[12px]">
              {delta > 0 ? (
                <TrendingUp className="h-3.5 w-3.5 text-danger" strokeWidth={2} aria-hidden />
              ) : (
                <TrendingDown className="h-3.5 w-3.5 text-success" strokeWidth={2} aria-hidden />
              )}
              <span className={delta > 0 ? "text-danger" : "text-success"}>
                {delta > 0 ? "+" : ""}
                {delta}
              </span>
            </div>
          )}
        </div>

        {topFactors.length > 0 && (
          <div className="mt-4 border-t border-hairline pt-3">
            <p className="mb-2 text-[11px] uppercase tracking-wide text-text-tertiary">
              Основные факторы
            </p>
            <div className="flex flex-col gap-1.5">
              {topFactors.map((f) => (
                <div key={f.factor} className="flex items-center justify-between gap-2">
                  <span className="truncate text-[13px] text-text-secondary">
                    {factorLabel(f.factor)}
                  </span>
                  <span className="whitespace-nowrap text-[12px] tabular-nums text-text-tertiary">
                    +{Math.round(f.contribution * 100)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {data.computed_at && (
          <p className="mt-3 text-[11px] text-text-tertiary">
            Обновлено {timeAgo(data.computed_at)}
          </p>
        )}
      </div>
    </Section>
  );
}
