import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { TopBar } from "../../app/layout/TopBar";
import { MONITORING_STREAM, useSse } from "../../shared/sse";
import type { AccountStatus } from "../../shared/types";
import { useAppContent } from "../more/AboutScreen";
import { dashboardApi } from "./api";
import type { Dashboard } from "./api";
import {
  ActivityRow,
  AlertCard,
  KpiTile,
  ModuleCard,
  StageCard,
  TrendChart,
} from "./components/cards";

const STAGES: AccountStatus[] = [
  "pool",
  "warming",
  "assigned",
  "cooldown",
  "banned",
  "created",
  "retired",
];

export function DashboardScreen() {
  const qc = useQueryClient();
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["dashboard"],
    queryFn: dashboardApi.get,
    refetchInterval: 30_000,
  });

  const onLive = useCallback(() => {
    qc.invalidateQueries({ queryKey: ["dashboard"] });
  }, [qc]);
  useSse(MONITORING_STREAM, onLive);

  return (
    <div className="min-h-full">
      <TopBar />
      <h1 className="screen-title mb-6 mt-1">Обзор</h1>

      {isLoading && <DashboardSkeleton />}

      {isError && !data && (
        <div className="card p-5 text-[13.5px] leading-snug text-text-primary">
          <p className="mb-1 font-semibold">Не удалось загрузить обзор</p>
          <p className="mb-4 text-text-secondary">
            {(error as Error | null)?.message ?? "Сервер API не отвечает."} Проверьте,
            что backend поднят на <span className="nums">localhost:8000</span>.
          </p>
          <button
            type="button"
            onClick={() => refetch()}
            className="rounded-pill border border-hairline bg-surface-2 px-4 py-2 text-[13px] font-semibold text-text-primary active:opacity-80"
          >
            Повторить
          </button>
        </div>
      )}

      {data && <DashboardContent data={data} />}
    </div>
  );
}

function DashboardContent({ data }: { data: Dashboard }) {
  const tz = useAppContent().data?.activity?.timezone;
  const k = data.kpis;

  // Алерты сворачиваем по (аккаунт + тип), чтобы повторы одной проблемы не
  // раздували ленту — показываем последнее событие и счётчик повторов.
  const groupedAlerts = (() => {
    const byKey = new Map<string, { alert: (typeof data.alerts)[number]; count: number }>();
    for (const a of data.alerts) {
      const key = `${a.account_id}:${a.event_type}`;
      const prev = byKey.get(key);
      if (!prev) byKey.set(key, { alert: a, count: 1 });
      else {
        prev.count += 1;
        if ((a.created_at ?? "") > (prev.alert.created_at ?? "")) prev.alert = a;
      }
    }
    return [...byKey.values()];
  })();

  return (
    <div className="flex flex-col gap-8">
      {/* KPI-плитки: сводка за сегодня одним взглядом. */}
      <section>
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-5">
          <KpiTile label="Действий сегодня" value={k.actions_today} />
          <KpiTile label="Активных кампаний" value={k.active_campaigns} tone="active" />
          <KpiTile label="Аккаунтов в работе" value={k.accounts_working} />
          <KpiTile label="Ошибок сегодня" value={k.errors_today} tone="critical" />
          <KpiTile label="Кампаний на паузе" value={k.paused_campaigns} tone="warning" />
        </div>
      </section>

      {/* 7-дневный тренд действий. */}
      <section>
        <SectionTitle>Тенденция</SectionTitle>
        <TrendChart points={data.trend_7d} />
      </section>

      {/* Аккаунты по статусам — авто-сетка без горизонтального скролла. */}
      <section>
        <SectionTitle>Аккаунты</SectionTitle>
        <div className="grid gap-2.5 [grid-template-columns:repeat(auto-fill,minmax(98px,1fr))] lg:grid-cols-7">
          {STAGES.map((s) => (
            <StageCard key={s} status={s} count={data.accounts_summary[s]} />
          ))}
        </div>
      </section>

      {/* Модули — все сразу, плоские карточки в адаптивной сетке. */}
      {data.modules_summary.length > 0 && (
        <section>
          <SectionTitle>Модули</SectionTitle>
          <div className="grid gap-3 lg:grid-cols-3">
            {data.modules_summary.map((m) => (
              <ModuleCard key={m.module} module={m} />
            ))}
          </div>
        </section>
      )}

      {/* Алерты и Активность — рядом на ПК, друг под другом на телефоне. */}
      <div className="grid gap-8 lg:grid-cols-2 lg:items-start">
        {groupedAlerts.length > 0 && (
          <section>
            <SectionTitle>Требует внимания</SectionTitle>
            <div className="flex flex-col gap-2">
              {groupedAlerts.map(({ alert, count }) => (
                <AlertCard
                  key={`${alert.account_id}:${alert.event_type}`}
                  alert={alert}
                  count={count}
                />
              ))}
            </div>
          </section>
        )}

        <section className={groupedAlerts.length > 0 ? "" : "lg:col-span-2"}>
          <SectionTitle>Активность</SectionTitle>
          {data.recent_activity.length > 0 ? (
            <div className="card max-h-[60vh] overflow-y-auto overflow-x-hidden p-0 [scrollbar-width:thin]">
              {data.recent_activity.slice(0, 20).map((item, i) => (
                <div key={i} className={i > 0 ? "border-t border-hairline" : ""}>
                  <ActivityRow item={item} tz={tz} />
                </div>
              ))}
            </div>
          ) : (
            <p className="px-1 text-[13px] text-text-tertiary">Пока тихо.</p>
          )}
        </section>
      </div>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2
      className="mb-4 text-[18px] font-bold leading-tight text-text-primary"
      style={{ letterSpacing: "-0.01em" }}
    >
      {children}
    </h2>
  );
}

function DashboardSkeleton() {
  return (
    <div className="flex flex-col gap-8">
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="card h-[74px] animate-pulse" />
        ))}
      </div>
      <div>
        <div className="mb-4 h-5 w-28 animate-pulse rounded-chip bg-surface-2" />
        <div className="card h-40 animate-pulse" />
      </div>
      <div>
        <div className="mb-4 h-5 w-24 animate-pulse rounded-chip bg-surface-2" />
        <div className="grid gap-2.5 [grid-template-columns:repeat(auto-fill,minmax(98px,1fr))] lg:grid-cols-7">
          {Array.from({ length: 7 }).map((_, i) => (
            <div key={i} className="card h-[92px] w-full animate-pulse" />
          ))}
        </div>
      </div>
      <div>
        <div className="mb-4 h-5 w-20 animate-pulse rounded-chip bg-surface-2" />
        <div className="grid gap-3 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="card h-28 animate-pulse" />
          ))}
        </div>
      </div>
    </div>
  );
}
