import { useQuery } from "@tanstack/react-query";
import { Lightbulb } from "lucide-react";
import { useMemo, useState } from "react";
import { accountsApi } from "../../../shared/accounts";
import { maskPhone, timeAgo } from "../../../shared/format";
import { SegmentedControl } from "../../commenting/components/ui";
import { shillingApi } from "../api";
import type { ExecutionLog, ExecutionStatus, Target } from "../types";

type StatusFilter = "all" | ExecutionStatus;

const FILTER_OPTS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "Все" },
  { value: "sent", label: "Успех" },
  { value: "failed", label: "Ошибки" },
  { value: "skipped", label: "Пропущ." },
];

export function HistoryTab({ campaignId }: { campaignId: number }) {
  const [filter, setFilter] = useState<StatusFilter>("all");

  const stats = useQuery({
    queryKey: ["shilling", "campaign", campaignId, "stats"],
    queryFn: () => shillingApi.stats(campaignId),
    refetchInterval: 10_000,
  });
  // Берём широкий срез для спарклайна и инсайтов.
  const logs = useQuery({
    queryKey: ["shilling", "campaign", campaignId, "logs", "history"],
    queryFn: () => shillingApi.logs(campaignId, { limit: 200 }),
    refetchInterval: 10_000,
  });
  const targets = useQuery({
    queryKey: ["shilling", "campaign", campaignId, "targets"],
    queryFn: () => shillingApi.targets(campaignId),
  });
  const accounts = useQuery({ queryKey: ["accounts", "all"], queryFn: () => accountsApi.list() });

  const allLogs: ExecutionLog[] = logs.data ?? [];
  const targetById = new Map((targets.data ?? []).map((t: Target) => [t.id, t]));
  const accById = new Map((accounts.data ?? []).map((a) => [a.id, a]));

  const s = stats.data;
  const days = useMemo(() => buildSparkline(allLogs), [allLogs]);
  const insights = useMemo(
    () => buildInsights(allLogs, targetById),
    [allLogs, targetById],
  );

  const shown = filter === "all" ? allLogs : allLogs.filter((l) => l.status === filter);

  return (
    <div className="flex flex-col gap-4">
      {/* Плитки */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Tile label="Всего попыток" value={s?.total ?? 0} />
        <Tile label="Успешно" value={s?.sent ?? 0} />
        <Tile label="Ошибки" value={s?.failed ?? 0} tone={s && s.failed > 0 ? "warn" : undefined} />
        <Tile label="Процент успеха" value={`${s?.success_rate_percent ?? 0}%`} />
      </div>

      {/* Спарклайн активности за 7 дней */}
      <div className="card p-4">
        <p className="mb-3 text-[13px] font-medium text-text-secondary">Активность за 7 дней</p>
        <div className="flex items-end gap-1.5" style={{ height: 56 }}>
          {days.map((d) => {
            const max = Math.max(1, ...days.map((x) => x.total));
            const h = Math.round((d.total / max) * 48) + 2;
            return (
              <div key={d.label} className="flex flex-1 flex-col items-center gap-1">
                <div
                  className="w-full rounded-t bg-accent/70"
                  style={{ height: h }}
                  title={`${d.label}: ${d.total}`}
                />
                <span className="text-[9px] text-text-tertiary">{d.label}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Инсайты */}
      {insights.length > 0 && (
        <div className="card flex flex-col gap-2 p-4">
          <p className="mb-1 flex items-center gap-1.5 text-[13px] font-medium text-text-secondary">
            <Lightbulb className="h-4 w-4 text-status-warning" strokeWidth={2} aria-hidden />
            Инсайты
          </p>
          {insights.map((text, i) => (
            <p key={i} className="text-[13px] text-text-tertiary">
              • {text}
            </p>
          ))}
        </div>
      )}

      {/* Лог */}
      <div className="card p-4">
        <div className="mb-3">
          <SegmentedControl options={FILTER_OPTS} value={filter} onChange={setFilter} />
        </div>
        {shown.length === 0 ? (
          <p className="py-6 text-center text-[13px] text-text-tertiary">Записей нет.</p>
        ) : (
          <div className="flex flex-col divide-y divide-hairline">
            {shown.slice(0, 100).map((log) => (
              <LogRow
                key={log.id}
                log={log}
                target={log.target_id != null ? targetById.get(log.target_id) : undefined}
                phone={accById.get(log.account_id)?.phone}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function LogRow({
  log,
  target,
  phone,
}: {
  log: ExecutionLog;
  target?: Target;
  phone?: string;
}) {
  const [open, setOpen] = useState(false);
  const dot =
    log.status === "sent"
      ? "bg-status-active"
      : log.status === "failed"
        ? "bg-status-critical"
        : "bg-status-neutral";
  const preview = log.message_text || log.error || "—";
  return (
    <button onClick={() => setOpen((v) => !v)} className="flex flex-col gap-1 py-2 text-left">
      <div className="flex items-center gap-2 text-[13px]">
        <span className={`h-2 w-2 shrink-0 rounded-full ${dot}`} aria-hidden />
        <span className="shrink-0 text-text-tertiary nums">{timeAgo(log.created_at)}</span>
        <span className="shrink-0 truncate text-text-secondary" style={{ maxWidth: 90 }}>
          {target?.title || target?.raw_input || "—"}
        </span>
        <span className="min-w-0 flex-1 truncate text-text-primary">
          {open ? "" : preview.slice(0, 60)}
        </span>
      </div>
      {open && (
        <div className="pl-4 text-[12px]">
          <p className="text-text-tertiary">
            {phone ? maskPhone(phone) : `Аккаунт #${log.account_id}`}
          </p>
          <p className="whitespace-pre-wrap text-text-primary">{preview}</p>
        </div>
      )}
    </button>
  );
}

function Tile({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: "warn";
}) {
  return (
    <div className="card p-3">
      <p className="text-[12px] text-text-tertiary">{label}</p>
      <p
        className={[
          "mt-1 text-[20px] font-bold nums",
          tone === "warn" ? "text-status-warning" : "text-text-primary",
        ].join(" ")}
      >
        {value}
      </p>
    </div>
  );
}

/* 7 дней (сегодня справа), количество попыток в день. */
function buildSparkline(logs: ExecutionLog[]): { label: string; total: number }[] {
  const buckets: { label: string; total: number; key: string }[] = [];
  const now = new Date();
  for (let i = 6; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(now.getDate() - i);
    const key = d.toISOString().slice(0, 10);
    buckets.push({ label: String(d.getDate()), total: 0, key });
  }
  const idx = new Map(buckets.map((b, i) => [b.key, i]));
  for (const log of logs) {
    const key = log.created_at.slice(0, 10);
    const i = idx.get(key);
    if (i != null) buckets[i].total += 1;
  }
  return buckets.map(({ label, total }) => ({ label, total }));
}

/* Простые клиентские инсайты: топ-цель по ошибкам + лучший аккаунт по успеху. */
function buildInsights(logs: ExecutionLog[], targetById: Map<number, Target>): string[] {
  const out: string[] = [];
  if (logs.length === 0) return out;

  const failByTarget = new Map<number, number>();
  const sentByAccount = new Map<number, number>();
  for (const log of logs) {
    if (log.status === "failed" && log.target_id != null) {
      failByTarget.set(log.target_id, (failByTarget.get(log.target_id) ?? 0) + 1);
    }
    if (log.status === "sent") {
      sentByAccount.set(log.account_id, (sentByAccount.get(log.account_id) ?? 0) + 1);
    }
  }
  const topFail = [...failByTarget.entries()].sort((a, b) => b[1] - a[1])[0];
  if (topFail && topFail[1] >= 2) {
    const t = targetById.get(topFail[0]);
    out.push(
      `Больше всего ошибок на «${t?.title || t?.raw_input || "цель #" + topFail[0]}» (${topFail[1]}) — возможно, строгие фильтры.`,
    );
  }
  const topAcc = [...sentByAccount.entries()].sort((a, b) => b[1] - a[1])[0];
  if (topAcc && topAcc[1] >= 3) {
    out.push(`Аккаунт #${topAcc[0]} даёт больше всего успешных отправок (${topAcc[1]}).`);
  }
  return out;
}
