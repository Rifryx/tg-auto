import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, Pause, Play, Rocket } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { haptic } from "../../shared/tg";
import { timeAgo } from "../../shared/format";
import { productsApi, shillingApi } from "./api";
import { AccountsTab } from "./components/AccountsTab";
import { BlacklistTab } from "./components/BlacklistTab";
import { DryRunSimulator } from "./components/DryRunSimulator";
import { HistoryTab } from "./components/HistoryTab";
import { ScenarioBuilder } from "./components/ScenarioBuilder";
import { TargetsTab } from "./components/TargetsTab";
import type { CampaignReadiness, CampaignStatus, ExecutionStatus } from "./types";

type Tab = "overview" | "scenario" | "accounts" | "targets" | "history" | "blacklist";

const TABS: { key: Tab; label: string }[] = [
  { key: "overview", label: "Обзор" },
  { key: "scenario", label: "Сценарий" },
  { key: "accounts", label: "Аккаунты" },
  { key: "targets", label: "Цели" },
  { key: "history", label: "История" },
  { key: "blacklist", label: "ЧС" },
];

const STATUS_META: Record<CampaignStatus, { label: string; dot: string; pulse: boolean }> = {
  draft: { label: "Черновик", dot: "bg-status-neutral", pulse: false },
  ready: { label: "Готова", dot: "bg-status-warning", pulse: false },
  running: { label: "Идёт", dot: "bg-status-active", pulse: true },
  paused: { label: "Пауза", dot: "bg-status-warning", pulse: false },
  completed: { label: "Завершена", dot: "bg-status-active", pulse: false },
  error: { label: "Ошибка", dot: "bg-status-critical", pulse: false },
};

export function ShillingDetailScreen() {
  const { id } = useParams();
  const campaignId = Number(id);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("overview");
  const [dryRunOpen, setDryRunOpen] = useState(false);

  const campaign = useQuery({
    queryKey: ["shilling", "campaign", campaignId],
    queryFn: () => shillingApi.get(campaignId),
  });
  const readiness = useQuery({
    queryKey: ["shilling", "campaign", campaignId, "readiness"],
    queryFn: () => shillingApi.readiness(campaignId),
    refetchInterval: 5000,
  });

  const toggle = useMutation({
    mutationFn: () =>
      campaign.data?.status === "running"
        ? shillingApi.stop(campaignId)
        : shillingApi.start(campaignId),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["shilling", "campaign", campaignId] }),
  });

  if (campaign.isLoading)
    return <div className="card mt-8 h-40 animate-pulse bg-surface-2" />;
  if (campaign.isError || !campaign.data)
    return (
      <p className="pt-10 text-center text-[14px] text-status-critical">
        Кампания не найдена.
      </p>
    );

  const c = campaign.data;
  const meta = STATUS_META[c.status];
  const isRunning = c.status === "running";

  return (
    <div className="pb-28 pt-1">
      <button
        onClick={() => navigate("/modules/shilling")}
        className="mb-3 inline-flex items-center gap-1 text-[14px] text-text-secondary active:text-text-primary"
      >
        <ArrowLeft className="h-4 w-4" strokeWidth={1.8} aria-hidden />
        Кампании
      </button>

      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <span
            className={["h-2.5 w-2.5 shrink-0 rounded-full", meta.dot, meta.pulse ? "animate-pulse" : ""].join(" ")}
            aria-hidden
          />
          <h1 className="screen-title truncate">{c.name}</h1>
        </div>
        <button
          onClick={() => {
            haptic("light");
            toggle.mutate();
          }}
          disabled={toggle.isPending || (!isRunning && !(readiness.data?.can_run ?? false))}
          className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-pill bg-surface-2 px-4 text-[14px] font-medium text-text-primary active:opacity-80 disabled:opacity-40"
        >
          {isRunning ? (
            <>
              <Pause className="h-4 w-4" strokeWidth={2} aria-hidden />
              Пауза
            </>
          ) : (
            <>
              <Play className="h-4 w-4" strokeWidth={2} aria-hidden />
              Запуск
            </>
          )}
        </button>
      </div>

      {/* Табы */}
      <div className="mb-5 -mx-4 overflow-x-auto px-4 [scrollbar-width:none]">
        <div className="flex gap-1.5">
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => {
                haptic("light");
                setTab(key);
              }}
              className={[
                "shrink-0 rounded-pill px-3.5 py-1.5 text-[13px] font-medium transition-colors",
                tab === key
                  ? "bg-surface-2 text-text-primary"
                  : "text-text-secondary hover:text-text-primary",
              ].join(" ")}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {tab === "overview" && <OverviewTab campaignId={campaignId} />}
      {tab === "scenario" && <ScenarioBuilder campaignId={campaignId} />}
      {tab === "accounts" && <AccountsTab campaignId={campaignId} />}
      {tab === "targets" && <TargetsTab campaignId={campaignId} />}
      {tab === "history" && <HistoryTab campaignId={campaignId} />}
      {tab === "blacklist" && <BlacklistTab campaignId={campaignId} />}

      <StickyLaunchPanel
        readiness={readiness.data}
        isRunning={isRunning}
        busy={toggle.isPending}
        onToggle={() => {
          haptic("light");
          toggle.mutate();
        }}
        onDryRun={() => setDryRunOpen(true)}
      />

      <DryRunSimulator
        open={dryRunOpen}
        campaignId={campaignId}
        onClose={() => setDryRunOpen(false)}
        onStart={() => {
          if (!isRunning) toggle.mutate();
        }}
      />
    </div>
  );
}

function OverviewTab({ campaignId }: { campaignId: number }) {
  const stats = useQuery({
    queryKey: ["shilling", "campaign", campaignId, "stats"],
    queryFn: () => shillingApi.stats(campaignId),
    refetchInterval: 5000,
  });
  const logs = useQuery({
    queryKey: ["shilling", "campaign", campaignId, "logs", "recent"],
    queryFn: () => shillingApi.logs(campaignId, { limit: 10 }),
    refetchInterval: 5000,
  });

  const s = stats.data;
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3">
        <Metric label="Отправлено" value={s?.sent ?? 0} />
        <Metric label="Ошибки" value={s?.failed ?? 0} tone={s && s.failed > 0 ? "warn" : undefined} />
        <Metric label="Всего попыток" value={s?.total ?? 0} />
        <Metric label="Успех" value={`${s?.success_rate_percent ?? 0}%`} />
      </div>

      <SettingsSection campaignId={campaignId} />

      <div className="card p-4">
        <p className="mb-3 text-[14px] font-medium text-text-primary">Последние отправки</p>
        {logs.data && logs.data.length > 0 ? (
          <div className="flex flex-col gap-2">
            {logs.data.map((log) => (
              <div key={log.id} className="flex items-center gap-2 text-[13px]">
                <LogDot status={log.status} />
                <span className="shrink-0 text-text-tertiary nums">{timeAgo(log.created_at)}</span>
                <span className="min-w-0 flex-1 truncate text-text-secondary">
                  {log.message_text || (log.status === "failed" ? log.error : "—")}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-[13px] text-text-tertiary">Пока нет отправок.</p>
        )}
      </div>
    </div>
  );
}

/** Настройки кампании — живые тогглы с автосохранением через PATCH.
    На каждый флип делаем optimistic update и сразу PATCH; при ошибке
    react-query откатит значение из последнего успешного ответа. */
function SettingsSection({ campaignId }: { campaignId: number }) {
  const qc = useQueryClient();
  const c = useQuery({
    queryKey: ["shilling", "campaign", campaignId],
    queryFn: () => shillingApi.get(campaignId),
  });
  const products = useQuery({
    queryKey: ["shilling", "products"],
    queryFn: productsApi.list,
  });

  const patch = useMutation({
    mutationFn: (body: Parameters<typeof shillingApi.update>[1]) =>
      shillingApi.update(campaignId, body),
    onSuccess: (updated) => {
      qc.setQueryData(["shilling", "campaign", campaignId], updated);
    },
  });

  if (!c.data) return null;
  const camp = c.data;

  return (
    <div className="card flex flex-col gap-3 p-4">
      <p className="text-[14px] font-medium text-text-primary">Настройки</p>

      <SettingRow
        label="Привязанный продукт"
        hint="Описание продукта попадёт в контекст LLM при генерации реплик."
      >
        <select
          value={camp.product_id ?? ""}
          onChange={(e) =>
            patch.mutate({
              product_id: e.target.value ? Number(e.target.value) : null,
            })
          }
          className="h-9 min-w-[200px] rounded-chip border border-hairline bg-surface-1 px-3 text-[13px] text-text-primary"
        >
          <option value="">— не выбран —</option>
          {(products.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </SettingRow>

      <SettingToggle
        label="Реакции между аккаунтами"
        hint="Боты ставят эмодзи-реакции на реплики друг друга — для большей естественности."
        checked={camp.inter_account_reactions_enabled}
        disabled={patch.isPending}
        onChange={(v) => patch.mutate({ inter_account_reactions_enabled: v })}
      />

      <SettingToggle
        label="Live Interception"
        hint="Если живой пользователь ответит реплаем на реплику бота — бот подхватит диалог и ответит."
        checked={camp.auto_responder !== "off"}
        disabled={patch.isPending}
        onChange={(v) =>
          patch.mutate({ auto_responder: v ? "reply_in_chat" : "off" })
        }
      />

      <SettingToggle
        label="Резервные аккаунты"
        hint="При peer_flood/спам-блоке активного аккаунта реплика переходит к резервному."
        checked={camp.reserve_enabled}
        disabled={patch.isPending}
        onChange={(v) => patch.mutate({ reserve_enabled: v })}
      />

      <SettingToggle
        label="Авто-прохождение капчи"
        hint="При вступлении в закрытый чат пытаемся решить капчу (button/math; image — через внешний провайдер)."
        checked={camp.captcha_solver_enabled}
        disabled={patch.isPending}
        onChange={(v) => patch.mutate({ captcha_solver_enabled: v })}
      />
    </div>
  );
}

function SettingRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="min-w-0 flex-1">
        <p className="text-[13px] text-text-primary">{label}</p>
        {hint && (
          <p className="mt-0.5 text-[11px] leading-relaxed text-text-tertiary">
            {hint}
          </p>
        )}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function SettingToggle({
  label,
  hint,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <SettingRow label={label} hint={hint}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={[
          "relative inline-flex h-[28px] w-[46px] shrink-0 items-center rounded-full border transition-colors disabled:opacity-50",
          checked
            ? "border-transparent bg-status-active"
            : "border-hairline bg-surface-2",
        ].join(" ")}
      >
        <span
          className={[
            "inline-block h-[22px] w-[22px] rounded-full bg-white shadow-sm transition-transform duration-150",
            checked ? "translate-x-[21px]" : "translate-x-[2px]",
          ].join(" ")}
        />
      </button>
    </SettingRow>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: "warn";
}) {
  return (
    <div className="card p-4">
      <p className="text-[12px] text-text-tertiary">{label}</p>
      <p
        className={[
          "mt-1 text-[24px] font-bold nums",
          tone === "warn" ? "text-status-warning" : "text-text-primary",
        ].join(" ")}
      >
        {value}
      </p>
    </div>
  );
}

function LogDot({ status }: { status: ExecutionStatus }) {
  const cls =
    status === "sent"
      ? "bg-status-active"
      : status === "failed"
        ? "bg-status-critical"
        : "bg-status-neutral";
  return <span className={`h-2 w-2 shrink-0 rounded-full ${cls}`} aria-hidden />;
}

function StickyLaunchPanel({
  readiness,
  isRunning,
  busy,
  onToggle,
  onDryRun,
}: {
  readiness?: CampaignReadiness;
  isRunning: boolean;
  busy: boolean;
  onToggle: () => void;
  onDryRun: () => void;
}) {
  const canRun = readiness?.can_run ?? false;
  const checks = readiness
    ? [readiness.accounts, readiness.scenario, readiness.targets]
    : [];
  return (
    <div
      /* На мобилке BottomNav (плавающая капсула, z-40) живёт у нижнего края —
         поднимаем readiness-bar выше неё (bottom +88px), чтобы не перекрывались.
         На десктопе BottomNav скрыт (lg:hidden в AppLayout), а слева стоит
         боковая панель (w-260px): прижимаем bar к самому низу и сдвигаем вправо
         на ширину панели, чтобы он был вровень с контентом, а не «криво». */
      className="fixed inset-x-0 bottom-[calc(env(safe-area-inset-bottom)_+_88px)] z-30 border-t border-hairline bg-bg-elevated px-4 pb-3 pt-3 lg:bottom-0 lg:left-[260px] lg:pb-[calc(env(safe-area-inset-bottom)_+_12px)]"
    >
      <div className="mx-auto flex max-w-3xl items-center justify-between gap-3">
        <div className="flex min-w-0 flex-wrap gap-x-3 gap-y-1">
          {checks.map((chk, i) => (
            <span key={i} className="inline-flex items-center gap-1 text-[12px]">
              <span
                className={[
                  "flex h-4 w-4 items-center justify-center rounded-full text-[9px]",
                  chk.ok ? "bg-status-active/20 text-status-active" : "bg-surface-2 text-text-tertiary",
                ].join(" ")}
              >
                {chk.ok ? <Check className="h-2.5 w-2.5" strokeWidth={3} aria-hidden /> : "○"}
              </span>
              <span className={chk.ok ? "text-text-secondary" : "text-text-tertiary"}>
                {chk.label}
              </span>
            </span>
          ))}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {!isRunning && (
            <button
              onClick={onDryRun}
              className="inline-flex h-10 items-center gap-1.5 rounded-pill bg-surface-2 px-4 text-[13px] font-medium text-text-secondary active:text-text-primary"
            >
              Сухой прогон
            </button>
          )}
          <button
            onClick={onToggle}
            disabled={busy || (!isRunning && !canRun)}
            className="inline-flex h-10 items-center gap-1.5 rounded-pill bg-accent px-5 text-[14px] font-semibold text-accent-on active:opacity-80 disabled:opacity-40"
          >
            {isRunning ? (
              <>
                <Pause className="h-4 w-4" strokeWidth={2.2} aria-hidden />
                Остановить
              </>
            ) : (
              <>
                <Rocket className="h-4 w-4" strokeWidth={2.2} aria-hidden />
                Запустить
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
