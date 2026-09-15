import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { TopBar } from "../../app/layout/TopBar";
import { MONITORING_STREAM, useSse } from "../../shared/sse";
import type { AccountStatus } from "../../shared/types";
import { dashboardApi } from "./api";
import { ActivityRow, AlertCard, ModuleCard, StageCard } from "./components/cards";

// Порядок стадий в KPI-скролле (сначала операционно важные).
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
    refetchInterval: 30_000, // фолбэк-обновление
  });

  // Живое обновление: на событие account_status/health_alert — сразу перезапрос.
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

      {data && (
        <>
          {(() => {
            // Схлопываем повторы: один алерт на пару (аккаунт, тип), самый свежий,
            // со счётчиком — иначе один мёртвый прокси заваливает весь экран.
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
              <section className="mb-8">
                <SectionTitle>Алерты</SectionTitle>
                <div className="flex flex-col gap-2">
                  {grouped.map(({ alert, count }) => (
                    <AlertCard key={`${alert.account_id}:${alert.event_type}`} alert={alert} count={count} />
                  ))}
                </div>
              </section>
            ) : null;
          })()}

          <section className="mb-8">
            <SectionTitle>Аккаунты по стадиям</SectionTitle>
            {/* overflow-hint: последняя карточка подглядывает справа за счёт скролла */}
            <div className="-mx-5 flex gap-3 overflow-x-auto px-5 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
              {STAGES.map((s) => (
                <StageCard key={s} status={s} count={data.accounts_summary[s]} />
              ))}
            </div>
          </section>

          {data.modules_summary.length > 0 && (
            <section className="mb-8">
              <SectionTitle>Модули</SectionTitle>
              <div className="flex flex-col gap-3">
                {data.modules_summary.map((m) => (
                  <ModuleCard key={m.module} module={m} />
                ))}
              </div>
            </section>
          )}

          <section className="mb-4">
            <SectionTitle>Активность</SectionTitle>
            {data.recent_activity.length > 0 ? (
              <div className="card px-4 py-1">
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
        </>
      )}
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-2.5 px-1 text-[13px] font-semibold uppercase tracking-wide text-text-tertiary">
      {children}
    </h2>
  );
}

function DashboardSkeleton() {
  // На светлой теме surface-2 близок к bg — оборачиваем каждую плашку в
  // «card» (hairline-обводка), чтобы скелетон был виден, а не сливался.
  return (
    <div className="flex flex-col gap-6">
      <div className="flex gap-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="card h-24 w-[128px] shrink-0 animate-pulse" />
        ))}
      </div>
      <div className="card h-28 animate-pulse" />
      <div className="card h-40 animate-pulse" />
    </div>
  );
}
