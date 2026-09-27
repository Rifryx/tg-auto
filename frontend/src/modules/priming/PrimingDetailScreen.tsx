import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { primingApi } from "./api";
import { StatusDot } from "./components/StatusDot";

/* Экран деталей кампании — приезжает на промптах 6.3/6.4 (Ход/Логи).
   Пока — минимальная шапка с именем/статусом + плейсхолдер табов. */
export function PrimingDetailScreen() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const numericId = Number(id);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["priming", "campaign", numericId],
    queryFn: () => primingApi.get(numericId),
    enabled: Number.isFinite(numericId),
  });

  return (
    <div className="min-h-full pb-24">
      <ScreenHeader
        title={data?.name ?? "Кампания"}
        action={
          <button
            type="button"
            onClick={() => navigate("/modules/priming")}
            className="inline-flex h-9 items-center gap-1.5 rounded-pill bg-surface-2 px-4 text-[14px] text-text-secondary active:text-text-primary"
          >
            <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
            Список
          </button>
        }
      />

      {isLoading && <div className="card h-24 animate-pulse bg-surface-2" />}
      {isError && (
        <p className="px-1 text-[14px] text-status-critical">
          Не удалось загрузить кампанию.
        </p>
      )}

      {data && (
        <div className="flex flex-col gap-3">
          <div className="card p-4">
            <div className="flex items-center gap-2">
              <StatusDot status={data.status} />
              <span className="text-[15px] font-medium text-text-primary">
                {data.status}
              </span>
              {data.dry_run && (
                <span className="ml-1 rounded-pill bg-surface-2 px-2 py-0.5 text-[10px] uppercase tracking-wider text-text-secondary">
                  dry-run
                </span>
              )}
            </div>
            <p className="mt-2 text-[13px] text-text-secondary">
              Триггер · <span className="text-text-primary">{data.trigger_action}</span>
            </p>
            <p className="text-[13px] text-text-secondary">
              Прогрев · <span className="text-text-primary">{data.warmup_profile}</span>
            </p>
            <p className="text-[13px] text-text-secondary">
              Дневной лимит · <span className="tabular-nums text-text-primary">{data.daily_limit_per_account}</span>
            </p>
          </div>
          <div className="card p-4">
            <p className="text-[14px] text-text-secondary">
              Полные табы «Настройка / Ход / Логи» приезжают на промптах 6.3–6.4
              (см. docs/priming-ui.md §6–§7).
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
