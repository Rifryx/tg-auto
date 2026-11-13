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
import type { HumanizerMode, PrimingCampaign, WarmupProfile } from "./types";

const WARMUP_LABEL: Record<WarmupProfile, string> = {
  cold: "Cold · медленно",
  warm: "Warm · средне",
  hot: "Hot · быстро",
};

const HUMANIZER_LABEL: Record<HumanizerMode, string> = {
  off: "Выкл · только действия",
  balanced: "Сбалансированный",
  aggressive: "Агрессивный · больше фоновой активности",
};

/* Строка-тумблер (чекбокс) для редактора кампании. */
function EditToggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-3 text-[13px] text-text-secondary">
      <span>{label}</span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-5 w-5 accent-accent"
      />
    </label>
  );
}

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
  const [humanizer, setHumanizer] = useState<HumanizerMode>(campaign.humanizer_mode);
  const [dailyLimit, setDailyLimit] = useState(String(campaign.daily_limit_per_account));
  // Задержки храним в секундах, редактируем в минутах (как при создании).
  const [delayMin, setDelayMin] = useState(String(Math.round(campaign.delay_between_targets_sec_min / 60)));
  const [delayMax, setDelayMax] = useState(String(Math.round(campaign.delay_between_targets_sec_max / 60)));
  const [quietOn, setQuietOn] = useState(campaign.quiet_hours_target);
  const [quietStart, setQuietStart] = useState(String(campaign.quiet_hours_start));
  const [quietEnd, setQuietEnd] = useState(String(campaign.quiet_hours_end));
  const [excludeBots, setExcludeBots] = useState(campaign.exclude_bots);
  const [excludeDeleted, setExcludeDeleted] = useState(campaign.exclude_deleted);
  const [excludeAdmins, setExcludeAdmins] = useState(campaign.exclude_admins);
  const [requireUsername, setRequireUsername] = useState(campaign.require_username);
  const [premiumOnly, setPremiumOnly] = useState(campaign.premium_only);
  const [dryRun, setDryRun] = useState(campaign.dry_run);

  // Пере-синхронизируем все поля при смене кампании/прилёте свежих данных.
  useEffect(() => {
    setName(campaign.name);
    setWarmup(campaign.warmup_profile);
    setHumanizer(campaign.humanizer_mode);
    setDailyLimit(String(campaign.daily_limit_per_account));
    setDelayMin(String(Math.round(campaign.delay_between_targets_sec_min / 60)));
    setDelayMax(String(Math.round(campaign.delay_between_targets_sec_max / 60)));
    setQuietOn(campaign.quiet_hours_target);
    setQuietStart(String(campaign.quiet_hours_start));
    setQuietEnd(String(campaign.quiet_hours_end));
    setExcludeBots(campaign.exclude_bots);
    setExcludeDeleted(campaign.exclude_deleted);
    setExcludeAdmins(campaign.exclude_admins);
    setRequireUsername(campaign.require_username);
    setPremiumOnly(campaign.premium_only);
    setDryRun(campaign.dry_run);
  }, [campaign]);

  const save = useMutation({
    mutationFn: () => {
      // Минуты → секунды; гарантируем max >= min (CheckConstraint на бэке).
      const dMin = Math.max(0, Number(delayMin) || 0) * 60;
      const dMax = Math.max(dMin, Math.max(0, Number(delayMax) || 0) * 60);
      const qStart = Math.min(23, Math.max(0, Number(quietStart) || 0));
      const qEnd = Math.min(24, Math.max(qStart + 1, Number(quietEnd) || 24));
      return primingApi.update(campaign.id, {
        name: name.trim() || campaign.name,
        warmup_profile: warmup,
        humanizer_mode: humanizer,
        daily_limit_per_account: Math.min(500, Math.max(1, Number(dailyLimit) || 1)),
        delay_between_targets_sec_min: dMin,
        delay_between_targets_sec_max: dMax,
        quiet_hours_target: quietOn,
        quiet_hours_start: qStart,
        quiet_hours_end: qEnd,
        exclude_bots: excludeBots,
        exclude_deleted: excludeDeleted,
        exclude_admins: excludeAdmins,
        require_username: requireUsername,
        premium_only: premiumOnly,
        dry_run: dryRun,
      });
    },
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
        <span className="text-[12px] text-text-tertiary">все параметры →</span>
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
        Антидетект (Humanizer)
        <div className="mt-1">
          <Select
            value={humanizer}
            onChange={(v) => setHumanizer(v as HumanizerMode)}
            options={(["off", "balanced", "aggressive"] as HumanizerMode[]).map((m) => ({
              value: m,
              label: HUMANIZER_LABEL[m],
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

      {/* Задержка между касаниями — в минутах (как при создании). */}
      <div className="grid grid-cols-2 gap-3">
        <label className="text-[13px] text-text-secondary">
          Пауза от, мин
          <input
            inputMode="numeric"
            value={delayMin}
            onChange={(e) => setDelayMin(e.target.value.replace(/\D/g, ""))}
            className="mt-1 w-full rounded-chip border border-hairline bg-surface-1 px-3 py-2.5 text-[14px] tabular-nums text-text-primary outline-none focus:border-strong"
          />
        </label>
        <label className="text-[13px] text-text-secondary">
          до, мин
          <input
            inputMode="numeric"
            value={delayMax}
            onChange={(e) => setDelayMax(e.target.value.replace(/\D/g, ""))}
            className="mt-1 w-full rounded-chip border border-hairline bg-surface-1 px-3 py-2.5 text-[14px] tabular-nums text-text-primary outline-none focus:border-strong"
          />
        </label>
      </div>

      {/* Тихие часы цели. */}
      <label className="flex items-center justify-between gap-3 text-[13px] text-text-secondary">
        <span>Тихие часы цели — не писать ночью</span>
        <input
          type="checkbox"
          checked={quietOn}
          onChange={(e) => setQuietOn(e.target.checked)}
          className="h-5 w-5 accent-accent"
        />
      </label>
      {quietOn && (
        <div className="grid grid-cols-2 gap-3">
          <label className="text-[13px] text-text-secondary">
            Тихо с, ч
            <input
              inputMode="numeric"
              value={quietStart}
              onChange={(e) => setQuietStart(e.target.value.replace(/\D/g, ""))}
              className="mt-1 w-full rounded-chip border border-hairline bg-surface-1 px-3 py-2.5 text-[14px] tabular-nums text-text-primary outline-none focus:border-strong"
            />
          </label>
          <label className="text-[13px] text-text-secondary">
            до, ч
            <input
              inputMode="numeric"
              value={quietEnd}
              onChange={(e) => setQuietEnd(e.target.value.replace(/\D/g, ""))}
              className="mt-1 w-full rounded-chip border border-hairline bg-surface-1 px-3 py-2.5 text-[14px] tabular-nums text-text-primary outline-none focus:border-strong"
            />
          </label>
        </div>
      )}

      {/* Фильтры аудитории. */}
      <p className="mt-1 text-[12px] font-medium text-text-tertiary">Кого не трогать</p>
      <EditToggle label="Исключить ботов" checked={excludeBots} onChange={setExcludeBots} />
      <EditToggle label="Исключить удалённые аккаунты" checked={excludeDeleted} onChange={setExcludeDeleted} />
      <EditToggle label="Исключить админов чатов" checked={excludeAdmins} onChange={setExcludeAdmins} />
      <EditToggle label="Только с @username" checked={requireUsername} onChange={setRequireUsername} />
      <EditToggle label="Только Telegram Premium" checked={premiumOnly} onChange={setPremiumOnly} />

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
