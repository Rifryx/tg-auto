import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Megaphone, MessagesSquare, Pause, Play, Plus } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { EmptyState } from "../../components/EmptyState";
import { LimitBanner } from "../../shared/LimitBanner";
import { timeAgo } from "../../shared/format";
import { haptic } from "../../shared/tg";
import { shillingApi } from "./api";
import type { Campaign, CampaignStatus } from "./types";

type Filter = "all" | "running" | "paused" | "draft";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "Все" },
  { key: "running", label: "Идут" },
  { key: "paused", label: "Пауза" },
  { key: "draft", label: "Черновики" },
];

const STATUS_META: Record<CampaignStatus, { label: string; dot: string; pulse: boolean }> = {
  draft: { label: "Черновик", dot: "bg-status-neutral", pulse: false },
  ready: { label: "Готова", dot: "bg-status-warning", pulse: false },
  running: { label: "Идёт", dot: "bg-status-active", pulse: true },
  paused: { label: "Пауза", dot: "bg-status-warning", pulse: false },
  completed: { label: "Завершена", dot: "bg-status-active", pulse: false },
  error: { label: "Ошибка", dot: "bg-status-critical", pulse: false },
};

function matchesFilter(c: Campaign, f: Filter): boolean {
  if (f === "all") return true;
  if (f === "running") return c.status === "running";
  if (f === "paused") return c.status === "paused";
  if (f === "draft") return c.status === "draft" || c.status === "ready";
  return true;
}

export function ShillingListScreen() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<Filter>("all");
  const { data, isLoading, isError } = useQuery({
    queryKey: ["shilling", "campaigns"],
    queryFn: shillingApi.list,
    refetchInterval: 15_000,
  });

  const shown = (data ?? []).filter((c) => matchesFilter(c, filter));

  return (
    <div className="min-h-full pb-6">
      <ScreenHeader
        title="НейроШиллинг"
        action={
          <button
            onClick={() => navigate("/modules/shilling/campaigns/new")}
            className="inline-flex h-9 items-center gap-1.5 rounded-pill bg-accent px-4 text-[14px] font-medium text-accent-on active:opacity-80"
          >
            <Plus className="h-4 w-4" strokeWidth={2.2} aria-hidden />
            Новая
          </button>
        }
      />

      <LimitBanner feature="shilling_campaigns_active_max" />

      <div className="mb-4 flex flex-wrap gap-2">
        {FILTERS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            className={[
              "rounded-pill px-3.5 py-1.5 text-[13px] font-medium transition-colors",
              filter === key
                ? "bg-surface-2 text-text-primary"
                : "text-text-secondary hover:text-text-primary",
            ].join(" ")}
          >
            {label}
          </button>
        ))}
      </div>

      {isLoading && (
        <div className="flex flex-col gap-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="card h-32 animate-pulse bg-surface-2" />
          ))}
        </div>
      )}

      {isError && (
        <p className="px-1 text-[14px] text-status-critical">Не удалось загрузить.</p>
      )}

      {data && shown.length > 0 && (
        <div className="flex flex-col gap-3">
          {shown.map((c) => (
            <ShillingCard key={c.id} campaign={c} />
          ))}
        </div>
      )}

      {data && shown.length === 0 && (
        <EmptyState
          icon={MessagesSquare}
          title={filter === "all" ? "Пока нет кампаний" : "Ничего не найдено"}
          hint={
            filter === "all"
              ? "Создайте кампанию шиллинга: сценарий диалога, аккаунты и цели."
              : "Смените фильтр или создайте новую кампанию."
          }
        />
      )}
    </div>
  );
}

function ShillingCard({ campaign: c }: { campaign: Campaign }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const meta = STATUS_META[c.status];

  const stats = useQuery({
    queryKey: ["shilling", "campaign", c.id, "stats"],
    queryFn: () => shillingApi.stats(c.id),
    refetchInterval: c.status === "running" ? 10_000 : false,
  });

  const toggle = useMutation({
    mutationFn: () => (c.status === "running" ? shillingApi.stop(c.id) : shillingApi.start(c.id)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["shilling", "campaigns"] });
    },
  });

  const canToggle = c.status === "running" || c.status === "paused" || c.status === "ready";
  const successRate = stats.data?.success_rate_percent ?? 0;

  return (
    <div className="card flex items-start gap-4 p-4">
      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-surface-2 text-text-primary">
        <Megaphone className="h-5 w-5" strokeWidth={1.7} aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <span
              className={[
                "h-2 w-2 shrink-0 rounded-full",
                meta.dot,
                meta.pulse ? "animate-pulse" : "",
              ].join(" ")}
              aria-hidden
            />
            <h3 className="truncate text-[15px] font-semibold leading-tight text-text-primary">{c.name}</h3>
          </div>
          <span className="shrink-0 rounded-pill bg-surface-2 px-2.5 py-1 text-[11px] font-medium text-text-secondary">
            {meta.label}
          </span>
        </div>

        {c.brand_name && (
          <p className="mb-1 truncate text-[13px] text-text-tertiary">
            Бренд: {c.brand_name}
          </p>
        )}

        {stats.data && stats.data.total > 0 && (
          <div className="mb-2">
            <div className="mb-1 flex items-center justify-between text-[12px] text-text-tertiary">
              <span>
                Отправлено {stats.data.sent}/{stats.data.total}
              </span>
              <span>Успех {successRate}%</span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-pill bg-surface-2">
              <div
                className="h-full rounded-pill bg-accent transition-all"
                style={{ width: `${successRate}%` }}
              />
            </div>
          </div>
        )}

        <div className="flex items-center justify-between gap-2">
          <span className="text-[12px] text-text-tertiary">
            {timeAgo(c.updated_at)}
          </span>
          <div className="flex items-center gap-2">
            {canToggle && (
              <button
                onClick={() => {
                  haptic("light");
                  toggle.mutate();
                }}
                disabled={toggle.isPending}
                className="inline-flex h-8 items-center gap-1 rounded-pill bg-surface-2 px-3 text-[13px] text-text-secondary active:text-text-primary disabled:opacity-50"
              >
                {c.status === "running" ? (
                  <>
                    <Pause className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
                    Пауза
                  </>
                ) : (
                  <>
                    <Play className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
                    Запуск
                  </>
                )}
              </button>
            )}
            <button
              onClick={() => navigate(`/modules/shilling/campaigns/${c.id}`)}
              className="inline-flex h-8 items-center gap-1 rounded-pill bg-accent px-3 text-[13px] font-medium text-accent-on active:opacity-80"
            >
              Открыть
              <ChevronRight className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
