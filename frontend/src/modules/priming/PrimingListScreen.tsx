import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BellRing, Copy, Plus, RotateCcw } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { EmptyState } from "../../components/EmptyState";
import { PLANS } from "../../shared/plans";
import { useUiStore } from "../../shared/store";
import { primingApi } from "./api";
import { CampaignCard } from "./components/CampaignCard";
import { PaywallCapsule } from "./components/PaywallCapsule";
import { StatusDot } from "./components/StatusDot";
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

const LONG_PRESS_MS = 700;

/* Экран «Кампании прайминга» (docs/priming-ui.md §4).
   Список карточек + пилюли-фильтры сверху + FAB `+` над навбаром;
   long-press по FAB (700 мс) открывает bottom-sheet «Повторить
   последнюю кампанию» (prompt 7.6). */
export function PrimingListScreen() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [filter, setFilter] = useState<Filter>("all");
  const planId = useUiStore((s) => s.planId);
  const primingEnabled = !!PLANS.find((p) => p.id === planId)?.limits
    .priming_enabled;
  const { data, isLoading, isError } = useCampaigns();
  const [showRepeatSheet, setShowRepeatSheet] = useState(false);
  const timerRef = useRef<number | null>(null);
  const triggeredLongPress = useRef(false);

  const shown = useMemo(
    () => (data ?? []).filter((c) => matchesFilter(c, filter)),
    [data, filter],
  );

  const lastFinished = useMemo(
    () =>
      (data ?? []).find(
        (c) =>
          c.status === "finished" ||
          c.status === "stopped" ||
          c.status === "paused",
      ) ?? null,
    [data],
  );

  const duplicate = useMutation({
    mutationFn: (id: number) => primingApi.duplicate(id),
    onSuccess: async (clone) => {
      qc.invalidateQueries({ queryKey: ["priming", "campaigns"] });
      try {
        await primingApi.start(clone.id);
      } catch {
        // если валидатор не пропустил — оставим draft и откроем экран
      }
      setShowRepeatSheet(false);
      navigate(`/modules/priming/campaigns/${clone.id}`);
    },
  });

  function startPress() {
    triggeredLongPress.current = false;
    if (timerRef.current) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => {
      triggeredLongPress.current = true;
      setShowRepeatSheet(true);
    }, LONG_PRESS_MS);
  }
  function endPress() {
    if (timerRef.current) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }
  function onClick() {
    if (triggeredLongPress.current) {
      triggeredLongPress.current = false;
      return;
    }
    navigate("/modules/priming/campaigns/new");
  }

  if (!primingEnabled) {
    return (
      <div className="min-h-full pb-24">
        <ScreenHeader title="Прайминг" />
        <PaywallCapsule />
      </div>
    );
  }

  return (
    <div className="min-h-full pb-24">
      <ScreenHeader title="Прайминг" />

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

      {/* FAB (long-press → повтор) */}
      <button
        type="button"
        onClick={onClick}
        onMouseDown={startPress}
        onMouseUp={endPress}
        onMouseLeave={endPress}
        onTouchStart={startPress}
        onTouchEnd={endPress}
        onTouchCancel={endPress}
        aria-label="Новая кампания (удерживать — повтор)"
        className="fixed right-4 z-20 flex h-14 w-14 items-center justify-center rounded-pill bg-accent text-accent-on shadow-lg active:opacity-80"
        style={{ bottom: "calc(env(safe-area-inset-bottom) + 80px)" }}
      >
        <Plus className="h-6 w-6" strokeWidth={2.4} aria-hidden />
      </button>

      {showRepeatSheet && (
        <div
          className="fixed inset-0 z-40 flex items-end bg-black/50"
          onClick={() => setShowRepeatSheet(false)}
        >
          <div
            className="w-full rounded-t-3xl border-t border-hairline bg-bg-elevated p-4"
            style={{
              paddingBottom: "calc(env(safe-area-inset-bottom) + 16px)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex items-center gap-2">
              <RotateCcw
                className="h-4 w-4 text-text-secondary"
                strokeWidth={2}
                aria-hidden
              />
              <div className="text-[15px] font-medium text-text-primary">
                Повторить последнюю кампанию
              </div>
            </div>
            {!lastFinished && (
              <p className="text-[13px] text-text-tertiary">
                Пока нет завершённых или остановленных кампаний.
              </p>
            )}
            {lastFinished && (
              <div className="rounded-2xl border border-hairline bg-surface-1 p-3">
                <div className="flex items-center gap-2">
                  <StatusDot status={lastFinished.status} />
                  <span className="text-[14px] font-medium text-text-primary">
                    {lastFinished.name}
                  </span>
                </div>
                <p className="mt-1 text-[12px] text-text-tertiary">
                  Триггер · {lastFinished.trigger_action} · Прогрев ·{" "}
                  {lastFinished.warmup_profile}
                </p>
                <button
                  type="button"
                  onClick={() => duplicate.mutate(lastFinished.id)}
                  disabled={duplicate.isPending}
                  className="mt-3 inline-flex h-10 items-center gap-1.5 rounded-pill bg-accent px-4 text-[14px] font-semibold text-accent-on disabled:opacity-50"
                >
                  <Copy className="h-4 w-4" strokeWidth={2.4} aria-hidden />
                  {duplicate.isPending
                    ? "Копирую…"
                    : "Запустить копию сейчас"}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
