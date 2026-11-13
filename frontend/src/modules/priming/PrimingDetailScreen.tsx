import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertOctagon,
  ArrowLeft,
  FileText,
  Pencil,
  Play,
  Square,
  Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { Select } from "../../shared/Select";
import { primingApi } from "./api";
import { StatusDot } from "./components/StatusDot";
import type { PrimingCampaign, WarmupProfile } from "./types";

const WARMUP_LABEL: Record<WarmupProfile, string> = {
  cold: "Cold · медленно",
  warm: "Warm · средне",
  hot: "Hot · быстро",
};

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

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["priming", "campaign", numericId] });
    qc.invalidateQueries({ queryKey: ["priming", "campaigns"] });
  };
  const resume = useMutation({
    mutationFn: () => primingApi.resume(numericId),
    onSuccess: invalidate,
  });
  const stop = useMutation({
    mutationFn: () => primingApi.stop(numericId),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: () => primingApi.remove(numericId),
    onSuccess: () => {
      invalidate();
      navigate("/modules/priming");
    },
  });

  const [confirmDelete, setConfirmDelete] = useState(false);

  // Статусы: редактировать можно в draft/paused, удалять — в
  // draft/stopped/finished/failed. Для running/paused сначала «Остановить».
  const editable = data?.status === "draft" || data?.status === "paused";
  const deletable =
    data?.status === "draft" ||
    data?.status === "stopped" ||
    data?.status === "finished" ||
    data?.status === "failed";
  const stoppable = data?.status === "running" || data?.status === "paused";

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
                <span className="ml-1 rounded-pill bg-surface-2 px-2 py-0.5 text-[10px] text-text-secondary">
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

          <button
            type="button"
            onClick={() =>
              navigate(`/modules/priming/campaigns/${numericId}/logs`)
            }
            className="card flex items-center justify-between p-4 text-left active:bg-surface-2"
          >
            <div className="flex items-center gap-2">
              <FileText
                className="h-4 w-4 text-text-secondary"
                strokeWidth={2}
                aria-hidden
              />
              <span className="text-[14px] font-medium text-text-primary">
                Логи и CSV экспорт
              </span>
            </div>
            <span className="text-[12px] text-text-tertiary">
              фильтры + ⤓ CSV →
            </span>
          </button>

          {/* Редактирование параметров — доступно в draft/paused. */}
          {editable ? (
            <EditCard campaign={data} onSaved={invalidate} />
          ) : (
            <div className="card p-4 text-[12px] text-text-tertiary">
              Параметры можно менять только в черновике или на паузе. Сейчас
              статус «{data.status}» — поставьте кампанию на паузу, чтобы
              отредактировать.
            </div>
          )}

          {/* Управление: остановить / удалить. */}
          <div className="card flex flex-col gap-2 p-4">
            {stoppable && (
              <button
                type="button"
                onClick={() => stop.mutate()}
                disabled={stop.isPending}
                className="inline-flex h-10 items-center justify-center gap-1.5 rounded-pill bg-surface-2 text-[14px] font-medium text-text-primary active:opacity-80 disabled:opacity-50"
              >
                <Square className="h-4 w-4" strokeWidth={2} aria-hidden />
                {stop.isPending ? "Останавливаю…" : "Остановить кампанию"}
              </button>
            )}
            {!confirmDelete ? (
              <button
                type="button"
                onClick={() => {
                  if (deletable) setConfirmDelete(true);
                }}
                disabled={!deletable}
                title={
                  deletable
                    ? undefined
                    : "Сначала остановите кампанию"
                }
                className="inline-flex h-10 items-center justify-center gap-1.5 rounded-pill border border-status-critical/40 text-[14px] font-medium text-status-critical active:opacity-80 disabled:opacity-40"
              >
                <Trash2 className="h-4 w-4" strokeWidth={2} aria-hidden />
                Удалить кампанию
              </button>
            ) : (
              <div className="flex flex-col gap-2 rounded-chip border border-status-critical/40 bg-status-critical/10 p-3">
                <p className="text-[13px] text-text-primary">
                  Удалить кампанию «{data.name}» безвозвратно? Все цели, аккаунты
                  и логи этой кампании будут удалены.
                </p>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setConfirmDelete(false)}
                    className="h-9 flex-1 rounded-pill bg-surface-2 text-[13px] text-text-secondary active:text-text-primary"
                  >
                    Отмена
                  </button>
                  <button
                    type="button"
                    onClick={() => remove.mutate()}
                    disabled={remove.isPending}
                    className="h-9 flex-1 rounded-pill bg-status-critical text-[13px] font-semibold text-white active:opacity-80 disabled:opacity-50"
                  >
                    {remove.isPending ? "Удаляю…" : "Удалить"}
                  </button>
                </div>
              </div>
            )}
            {remove.isError && (
              <p className="text-[12px] text-status-critical">
                Не удалось удалить. Убедитесь, что кампания остановлена.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* Инлайн-редактор ключевых параметров кампании (draft/paused). */
function EditCard({
  campaign,
  onSaved,
}: {
  campaign: PrimingCampaign;
  onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(campaign.name);
  const [warmup, setWarmup] = useState<WarmupProfile>(campaign.warmup_profile);
  const [dailyLimit, setDailyLimit] = useState(String(campaign.daily_limit_per_account));
  const [dryRun, setDryRun] = useState(campaign.dry_run);
  useEffect(() => {
    setName(campaign.name);
    setWarmup(campaign.warmup_profile);
    setDailyLimit(String(campaign.daily_limit_per_account));
    setDryRun(campaign.dry_run);
  }, [campaign.id, campaign.name, campaign.warmup_profile, campaign.daily_limit_per_account, campaign.dry_run]);

  const save = useMutation({
    mutationFn: () =>
      primingApi.update(campaign.id, {
        name: name.trim() || campaign.name,
        warmup_profile: warmup,
        daily_limit_per_account: Math.max(1, Number(dailyLimit) || 1),
        dry_run: dryRun,
      }),
    onSuccess: () => {
      onSaved();
      setOpen(false);
    },
  });

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="card flex items-center justify-between p-4 text-left active:bg-surface-2"
      >
        <div className="flex items-center gap-2">
          <Pencil className="h-4 w-4 text-text-secondary" strokeWidth={2} aria-hidden />
          <span className="text-[14px] font-medium text-text-primary">
            Редактировать кампанию
          </span>
        </div>
        <span className="text-[12px] text-text-tertiary">имя, прогрев, лимит →</span>
      </button>
    );
  }

  return (
    <div className="card flex flex-col gap-3 p-4">
      <label className="text-[13px] text-text-secondary">
        Название
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="mt-1 w-full rounded-chip border border-hairline bg-surface-1 px-3 py-2.5 text-[14px] text-text-primary outline-none focus:border-strong"
        />
      </label>
      <label className="text-[13px] text-text-secondary">
        Профиль прогрева
        <div className="mt-1">
          <Select
            value={warmup}
            onChange={(v) => setWarmup(v as WarmupProfile)}
            options={(["cold", "warm", "hot"] as WarmupProfile[]).map((p) => ({
              value: p,
              label: WARMUP_LABEL[p],
            }))}
          />
        </div>
      </label>
      <label className="text-[13px] text-text-secondary">
        Дневной лимит на аккаунт
        <input
          inputMode="numeric"
          value={dailyLimit}
          onChange={(e) => setDailyLimit(e.target.value.replace(/\D/g, ""))}
          className="mt-1 w-full rounded-chip border border-hairline bg-surface-1 px-3 py-2.5 text-[14px] tabular-nums text-text-primary outline-none focus:border-strong"
        />
      </label>
      <label className="flex items-center justify-between gap-3 text-[13px] text-text-secondary">
        <span>Пробный запуск (dry-run) — без реальной отправки</span>
        <input
          type="checkbox"
          checked={dryRun}
          onChange={(e) => setDryRun(e.target.checked)}
          className="h-5 w-5 accent-accent"
        />
      </label>
      {save.isError && (
        <p className="text-[12px] text-status-critical">
          Не удалось сохранить. Параметры меняются только в черновике или на паузе.
        </p>
      )}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="h-10 flex-1 rounded-pill bg-surface-2 text-[14px] text-text-secondary active:text-text-primary"
        >
          Отмена
        </button>
        <button
          type="button"
          onClick={() => save.mutate()}
          disabled={save.isPending}
          className="h-10 flex-1 rounded-pill bg-accent text-[14px] font-semibold text-accent-on active:opacity-80 disabled:opacity-50"
        >
          {save.isPending ? "Сохраняю…" : "Сохранить"}
        </button>
      </div>
    </div>
  );
}
