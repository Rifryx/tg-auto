import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, AlertOctagon, ArrowLeft, Play } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { primingApi } from "./api";
import { StatusDot } from "./components/StatusDot";

/* Экран деталей кампании — приезжает на промптах 6.3/6.4 (Ход/Логи).
   Пока — минимальная шапка с именем/статусом + плейсхолдер табов. */
export function PrimingDetailScreen() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const numericId = Number(id);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["priming", "campaign", numericId],
    queryFn: () => primingApi.get(numericId),
    enabled: Number.isFinite(numericId),
  });

  const resume = useMutation({
    mutationFn: () => primingApi.resume(numericId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["priming", "campaign", numericId] });
      qc.invalidateQueries({ queryKey: ["priming", "campaigns"] });
    },
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
          {data.status === "paused" && (
            <div className="card flex items-start gap-3 border-l-[4px] border-status-critical bg-surface-1 p-4">
              <AlertOctagon
                className="mt-0.5 h-5 w-5 shrink-0 text-status-critical"
                strokeWidth={2}
                aria-hidden
              />
              <div className="min-w-0 flex-1">
                <div className="text-[14px] font-medium text-text-primary">
                  Кампания на автопаузе
                </div>
                <p className="mt-1 text-[12px] text-text-tertiary">
                  Сработал автостоп: скорее всего слишком высокая доля
                  privacy_restricted или flood_wait за последнее окно.
                  Проверьте логи и профиль прогрева перед возобновлением.
                </p>
                <button
                  type="button"
                  onClick={() => resume.mutate()}
                  disabled={resume.isPending}
                  className="mt-3 inline-flex h-9 items-center gap-1.5 rounded-pill bg-accent px-4 text-[13px] font-semibold text-accent-on disabled:opacity-50"
                >
                  <Play className="h-3.5 w-3.5" strokeWidth={2.5} aria-hidden />
                  {resume.isPending ? "Возобновляю…" : "Понял, продолжить"}
                </button>
              </div>
            </div>
          )}
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
          <button
            type="button"
            onClick={() =>
              navigate(`/modules/priming/campaigns/${numericId}/run`)
            }
            className="card flex items-center justify-between p-4 text-left active:bg-surface-2"
          >
            <div className="flex items-center gap-2">
              <Activity
                className="h-4 w-4 text-text-secondary"
                strokeWidth={2}
                aria-hidden
              />
              <span className="text-[14px] font-medium text-text-primary">
                Открыть «Ход»
              </span>
            </div>
            <span className="text-[12px] text-text-tertiary">
              KPI, sparkline, аккаунты →
            </span>
          </button>
        </div>
      )}
    </div>
  );
}
