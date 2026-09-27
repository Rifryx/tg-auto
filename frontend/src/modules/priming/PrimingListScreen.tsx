import { BellRing, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { EmptyState } from "../../components/EmptyState";
import { CampaignCard } from "./components/CampaignCard";
import { useCampaigns } from "./hooks/useCampaigns";
import type { PrimingCampaign } from "./types";

type Filter = "all" | "running" | "paused" | "draft";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "Все" },
  { key: "running", label: "Идут" },
  { key: "paused", label: "Пауза" },
  { key: "draft", label: "Черновики" },
];

function matchesFilter(c: PrimingCampaign, f: Filter): boolean {
  if (f === "all") return true;
  if (f === "running") return c.status === "running";
  if (f === "paused") return c.status === "paused";
  if (f === "draft") return c.status === "draft" || c.status === "queued";
  return true;
}

/* Экран «Кампании прайминга» (docs/priming-ui.md §4).
   Список карточек + пилюли-фильтры сверху + FAB `+` над навбаром. */
export function PrimingListScreen() {
  const navigate = useNavigate();
  const [filter, setFilter] = useState<Filter>("all");
  const { data, isLoading, isError } = useCampaigns();

  const shown = useMemo(
    () => (data ?? []).filter((c) => matchesFilter(c, filter)),
    [data, filter],
  );

  return (
    <div className="min-h-full pb-24">
      <ScreenHeader
        title="Прайминг"
        action={
          <button
            type="button"
            onClick={() => navigate("/modules/priming/campaigns/new")}
            className="inline-flex h-9 items-center gap-1.5 rounded-pill bg-accent px-4 text-[14px] font-medium text-accent-on active:opacity-80"
          >
            <Plus className="h-4 w-4" strokeWidth={2.2} aria-hidden />
            Новая
          </button>
        }
      />

      <div className="mb-4 flex flex-wrap gap-2">
        {FILTERS.map(({ key, label }) => (
          <button
            key={key}
            type="button"
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
            <div key={i} className="card h-24 animate-pulse bg-surface-2" />
          ))}
        </div>
      )}

      {isError && (
        <p className="px-1 text-[14px] text-status-critical">
          Не удалось загрузить кампании.
        </p>
      )}

      {data && shown.length > 0 && (
        <div className="flex flex-col gap-3">
          {shown.map((c) => (
            <CampaignCard key={c.id} campaign={c} />
          ))}
        </div>
      )}

      {data && shown.length === 0 && (
        <EmptyState
          icon={BellRing}
          title={filter === "all" ? "Пока нет кампаний" : "Ничего не найдено"}
          hint={
            filter === "all"
              ? "Создайте кампанию прайминга: выберите триггер, аккаунты и цели."
              : "Смените фильтр или создайте новую кампанию."
          }
        />
      )}
    </div>
  );
}
