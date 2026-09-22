import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BarChart3,
  Hash,
  MessageSquare,
  Pause,
  Play,
  Timer,
  Users,
  XCircle,
} from "lucide-react";
import { commentingApi } from "../api";
import { CapsuleButton, Section } from "./ui";

/* Блок «Запуск и логи» + карточка статистики (§ Этап 6).
 *
 * По образцу конкурента (скрины 4-5): 4 чипа с runtime-сводкой
 * (аккаунты / каналы / макс.интервал / макс.комментариев), кнопка
 * Старт/Пауза и 4 стат-тайла (всего/успех/ошибки/%). Данные тянутся
 * из /campaigns/{id}/stats и /runtime-summary (invalidate после
 * enable-toggle). */

export function LaunchAndStats({ campaignId }: { campaignId: number }) {
  const qc = useQueryClient();
  const summary = useQuery({
    queryKey: ["campaign", campaignId, "runtime-summary"],
    queryFn: () => commentingApi.runtimeSummary(campaignId),
    refetchInterval: 20_000,
  });
  const stats = useQuery({
    queryKey: ["campaign", campaignId, "stats"],
    queryFn: () => commentingApi.stats(campaignId),
    refetchInterval: 20_000,
  });
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => commentingApi.update(campaignId, { enabled }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["campaign", campaignId] });
      qc.invalidateQueries({ queryKey: ["campaign", campaignId, "runtime-summary"] });
    },
  });

  const s = summary.data;
  const enabled = s?.enabled ?? false;
  const canStart = (s?.accounts_count ?? 0) > 0 && (s?.channels_count ?? 0) > 0;

  return (
    <>
      <Section title="Запуск и логи">
        <div className="card p-4">
          <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-4">
            <RuntimeChip
              icon={<Users className="h-4 w-4" strokeWidth={2} aria-hidden />}
              label="Аккаунты"
              value={s?.accounts_count ?? "—"}
              warn={s?.accounts_count === 0}
            />
            <RuntimeChip
              icon={<Hash className="h-4 w-4" strokeWidth={2} aria-hidden />}
              label="Каналы"
              value={s?.channels_count ?? "—"}
              warn={s?.channels_count === 0}
            />
            <RuntimeChip
              icon={<Timer className="h-4 w-4" strokeWidth={2} aria-hidden />}
              label="Макс. интервал"
              value={s ? `${s.max_interval_sec}s` : "—"}
            />
            <RuntimeChip
              icon={<MessageSquare className="h-4 w-4" strokeWidth={2} aria-hidden />}
              label="Макс. комментариев"
              value={s?.max_comments ?? "∞"}
            />
          </div>
          <div className="flex items-center gap-2">
            <CapsuleButton
              variant={enabled ? "secondary" : canStart ? "accent" : "secondary"}
              disabled={(!enabled && !canStart) || toggle.isPending}
              onClick={() => toggle.mutate(!enabled)}
            >
              <span className="inline-flex items-center gap-2">
                {enabled ? (
                  <>
                    <Pause className="h-4 w-4" strokeWidth={2} aria-hidden /> Пауза
                  </>
                ) : (
                  <>
                    <Play className="h-4 w-4" strokeWidth={2} aria-hidden /> Запустить
                  </>
                )}
              </span>
            </CapsuleButton>
          </div>
          {!canStart && !enabled && (
            <p className="mt-3 rounded-chip border border-status-critical/40 bg-status-critical/10 px-3 py-2 text-[12px] text-status-critical">
              Проблемы с конфигурацией:{" "}
              {s?.accounts_count === 0 && "аккаунты не выбраны"}
              {s?.accounts_count === 0 && s?.channels_count === 0 && " · "}
              {s?.channels_count === 0 && "каналы не указаны"}
            </p>
          )}
        </div>
      </Section>

      <Section title="Статистика">
        <div className="card p-4">
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <StatTile
              icon={<MessageSquare className="h-4 w-4" strokeWidth={1.8} aria-hidden />}
              label="Всего попыток"
              value={stats.data?.total ?? 0}
            />
            <StatTile
              icon={<BarChart3 className="h-4 w-4 text-status-active" strokeWidth={1.8} aria-hidden />}
              label="Успешных"
              value={stats.data?.posted ?? 0}
              tone="ok"
            />
            <StatTile
              icon={<XCircle className="h-4 w-4 text-status-critical" strokeWidth={1.8} aria-hidden />}
              label="Неуспешных"
              value={(stats.data?.failed ?? 0) + (stats.data?.flagged ?? 0)}
              tone="risk"
            />
            <StatTile
              icon={<BarChart3 className="h-4 w-4" strokeWidth={1.8} aria-hidden />}
              label="Процент успешных"
              value={`${stats.data?.success_rate_percent ?? 0}%`}
            />
          </div>
        </div>
      </Section>
    </>
  );
}

function RuntimeChip({
  icon,
  label,
  value,
  warn,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  warn?: boolean;
}) {
  return (
    <div
      className={`rounded-chip border px-3 py-2 ${
        warn
          ? "border-status-critical/40 bg-status-critical/10"
          : "border-hairline bg-surface-1"
      }`}
    >
      <div className="mb-0.5 flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-text-tertiary">
        {icon}
        <span>{label}</span>
      </div>
      <p
        className={`text-[18px] font-semibold tabular-nums ${
          warn ? "text-status-critical" : "text-text-primary"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function StatTile({
  icon,
  label,
  value,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  tone?: "ok" | "risk";
}) {
  return (
    <div className="rounded-chip border border-hairline bg-surface-1 px-3 py-2">
      <div className="mb-1 flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-text-tertiary">
        {icon}
        <span>{label}</span>
      </div>
      <p
        className={`text-[22px] font-semibold tabular-nums ${
          tone === "ok"
            ? "text-status-active"
            : tone === "risk"
            ? "text-status-critical"
            : "text-text-primary"
        }`}
      >
        {value}
      </p>
    </div>
  );
}
