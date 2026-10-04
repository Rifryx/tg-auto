import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { TopBar } from "../../app/layout/TopBar";
import { MONITORING_STREAM, useSse } from "../../shared/sse";
import type { AccountStatus } from "../../shared/types";
import { dashboardApi } from "./api";
import type { Dashboard } from "./api";
import { ActivityRow, AlertCard, ModuleCard, StageCard } from "./components/cards";

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
      <h1 className="screen-title mb-8 mt-1">Обзор</h1>

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
  const total = Object.values(data.accounts_summary).reduce((a, b) => a + b, 0);
  const activeModules = data.modules_summary.filter((m) => m.active_now > 0).length;

  return (
    <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-start lg:gap-8">
      {/* Hero stats card */}
      <section className="mb-8 lg:col-span-2">
        <div className="card-hero flex items-center gap-6 p-6">
          <HeroStat value={total} label="Аккаунтов" />
          <div className="h-10 w-px border-l border-hairline" />
          <HeroStat value={activeModules} label="Модулей активно" />
          <div className="h-10 w-px border-l border-hairline" />
          <HeroStat
            value={data.modules_summary.reduce((a, m) => a + m.today_actions, 0)}
            label="Действий сегодня"
          />
        </div>
      </section>

      {/* Alerts */}
      {(() => {
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
        const grouped = [...byKey.values()];
        return grouped.length > 0 ? (
          <section className="mb-8 lg:col-span-2">
            <SectionTitle>Алерты</SectionTitle>
            <div className="flex flex-col gap-2">
              {grouped.map(({ alert, count }) => (
                <AlertCard key={`${alert.account_id}:${alert.event_type}`} alert={alert} count={count} />
              ))}
            </div>
          </section>
        ) : null;
      })()}

      {/* Accounts by stage */}
      <section className="mb-10 lg:col-span-2">
        <SectionTitle>Аккаунты</SectionTitle>
        <div className="-mx-5 flex gap-3 overflow-x-auto px-5 pb-1 lg:mx-0 lg:grid lg:grid-cols-7 lg:gap-3 lg:overflow-visible lg:px-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {STAGES.map((s) => (
            <StageCard key={s} status={s} count={data.accounts_summary[s]} />
          ))}
        </div>
      </section>

      {/* Modules */}
      {data.modules_summary.length > 0 && (
        <section className="mb-10 lg:mb-0">
          <SectionTitle>Модули</SectionTitle>
          <div className="flex flex-col gap-3">
            {data.modules_summary.map((m) => (
              <ModuleCard key={m.module} module={m} />
            ))}
          </div>
        </section>
      )}

      {/* Activity feed */}
      <section className="mb-4 lg:mb-0">
        <SectionTitle>Активность</SectionTitle>
        {data.recent_activity.length > 0 ? (
          <div className="card overflow-hidden p-0">
            {data.recent_activity.slice(0, 20).map((item, i) => (
              <div key={i} className={i > 0 ? "border-t border-hairline" : ""}>
                <ActivityRow item={item} />
              </div>
            ))}
          </div>
        ) : (
          <p className="px-1 text-[13px] text-text-tertiary">Пока тихо.</p>
        )}
      </section>
    </div>
  );
}

function HeroStat({ value, label }: { value: number; label: string }) {
  return (
    <div className="min-w-0 flex-1 text-center">
      <p className="nums text-[28px] font-bold leading-none text-text-primary">{value}</p>
      <p className="mt-1.5 truncate text-[12px] text-text-tertiary">{label}</p>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2
      className="mb-4 text-[22px] font-bold leading-tight text-text-primary"
      style={{ letterSpacing: "-0.01em" }}
    >
      {children}
    </h2>
  );
}

function DashboardSkeleton() {
  return (
    <div className="flex flex-col gap-8">
      <div className="card-hero flex items-center gap-6 p-6">
        {[1, 2, 3].map((i) => (
          <div key={i} className="flex-1 text-center">
            <div className="mx-auto h-8 w-12 animate-pulse rounded-chip bg-surface-2" />
            <div className="mx-auto mt-2 h-3 w-16 animate-pulse rounded bg-surface-2" />
          </div>
        ))}
      </div>
      <div>
        <div className="mb-4 h-7 w-32 animate-pulse rounded-chip bg-surface-2" />
        <div className="-mx-5 flex gap-3 overflow-hidden px-5 lg:mx-0 lg:grid lg:grid-cols-7 lg:px-0">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="card h-[110px] w-[140px] shrink-0 animate-pulse lg:h-28 lg:w-auto" />
          ))}
        </div>
      </div>
      <div>
        <div className="mb-4 h-7 w-24 animate-pulse rounded-chip bg-surface-2" />
        <div className="card h-32 animate-pulse" />
      </div>
    </div>
  );
}
