import {
  Activity,
  AlertTriangle,
  Ban,
  ChevronRight,
  KeyRound,
  MailX,
  Megaphone,
  MessagesSquare,
  ShieldAlert,
  Timer,
  WifiOff,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { maskPhone } from "../../../shared/format";
import { STATUS_LABEL, statusDotClass } from "../../../shared/status";
import type { AccountStatus } from "../../../shared/types";
import type { Alert, ActivityItem, ModuleSummary } from "../api";

const EVENT_ICON: Record<string, LucideIcon> = {
  flood_wait: Timer,
  spam_block: ShieldAlert,
  restricted: Ban,
  proxy_down: WifiOff,
  session_revoked: KeyRound,
  auth_failed: KeyRound,
  "commenting.not_subscribed": MailX,
  "commenting.access_lost": Ban,
  "commenting.blacklisted": Ban,
};
const EVENT_LABEL: Record<string, string> = {
  flood_wait: "Флуд-контроль",
  spam_block: "Спам-блок",
  restricted: "Ограничение",
  proxy_down: "Прокси недоступен",
  session_revoked: "Сессия сброшена",
  auth_failed: "Ошибка входа",
  "commenting.not_subscribed": "Не подписан на канал",
  "commenting.access_lost": "Нет доступа к обсуждению",
  "commenting.blacklisted": "Канал ушёл в чёрный список",
};

const STATUS_BAR: Record<string, string> = {
  active: "bg-status-active",
  warning: "bg-status-warning",
  critical: "bg-status-critical",
  neutral: "bg-status-neutral",
};

const STATUS_TONE_MAP: Record<AccountStatus, string> = {
  pool: "active",
  assigned: "active",
  warming: "warning",
  cooldown: "warning",
  banned: "critical",
  created: "neutral",
  retired: "neutral",
};

export function AlertCard({ alert, count = 1 }: { alert: Alert; count?: number }) {
  const Icon = EVENT_ICON[alert.event_type] ?? AlertTriangle;
  const bar = alert.severity === "critical" ? "bg-status-critical" : "bg-status-warning";
  const tone = alert.severity === "critical" ? "text-status-critical" : "text-status-warning";
  const campaignId = alert.event_type.startsWith("commenting.") ? alert.meta?.campaign_id : null;
  const channel = typeof alert.meta?.channel === "string" ? alert.meta.channel : null;
  const who = alert.phone ? maskPhone(alert.phone) : `Аккаунт #${alert.account_id}`;
  return (
    <Link
      to={campaignId ? `/modules/commenting/campaigns/${campaignId}` : `/accounts/${alert.account_id}`}
      className="card relative flex items-center gap-3 overflow-hidden py-3.5 pl-5 pr-4 active:bg-surface-2"
    >
      <span className={`absolute inset-y-0 left-0 w-1 ${bar}`} aria-hidden />
      <Icon className={`h-5 w-5 shrink-0 ${tone}`} strokeWidth={1.8} aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[14px] font-semibold text-text-primary">
          {EVENT_LABEL[alert.event_type] ?? alert.event_type}
        </p>
        <p className="mt-0.5 truncate text-[12px] text-text-tertiary nums">
          {channel ? `${who} · ${channel}` : who}
        </p>
      </div>
      {count > 1 && (
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-[12px] font-semibold tabular-nums ${tone}`}
          style={{ background: "color-mix(in srgb, currentColor 16%, transparent)" }}
        >
          ×{count}
        </span>
      )}
      <ChevronRight className="h-4 w-4 text-text-tertiary" strokeWidth={1.8} aria-hidden />
    </Link>
  );
}

export function StageCard({ status, count }: { status: AccountStatus; count: number }) {
  const tone = STATUS_TONE_MAP[status];
  const barClass = STATUS_BAR[tone];
  return (
    <Link
      to={`/accounts?status=${status}`}
      className="card relative flex w-[140px] shrink-0 flex-col justify-between overflow-hidden p-4 active:bg-surface-2 lg:w-auto"
      style={{ minHeight: 110 }}
    >
      <span className={`absolute inset-y-0 left-0 w-[3px] ${barClass}`} aria-hidden />
      <div className="flex items-center gap-1.5 pl-1">
        <span className={`h-2 w-2 shrink-0 rounded-full ${statusDotClass(status)}`} aria-hidden />
        <span className="truncate text-[13px] text-text-secondary">
          {STATUS_LABEL[status]}
        </span>
      </div>
      <span className="nums pl-1 text-[32px] font-bold leading-none text-text-primary lg:text-[34px]">
        {count}
      </span>
    </Link>
  );
}

const MODULE_META: Record<string, { label: string; icon: LucideIcon; to: string }> = {
  commenting: { label: "Комментирование", icon: MessagesSquare, to: "/tasks" },
  shilling: { label: "НейроШиллинг", icon: Megaphone, to: "/modules/shilling" },
};

export function ModuleCard({ module }: { module: ModuleSummary }) {
  const meta = MODULE_META[module.module];
  const Icon = meta?.icon ?? MessagesSquare;
  return (
    <Link
      to={meta?.to ?? "/tasks"}
      className="card-hero flex items-center gap-4 p-5 active:opacity-90"
    >
      <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-surface-2 text-text-primary">
        <Icon className="h-6 w-6" strokeWidth={1.5} aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <span className="text-[16px] font-bold text-text-primary">
          {meta?.label ?? module.module}
        </span>
        <div className="mt-2 flex gap-5">
          <Metric label="Кампаний" value={module.instances} />
          <Metric label="В работе" value={module.active_now} />
          <Metric label="Сегодня" value={module.today_actions} />
        </div>
      </div>
      <ChevronRight className="h-4 w-4 shrink-0 text-text-tertiary" strokeWidth={1.8} aria-hidden />
    </Link>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <p className="nums text-[20px] font-bold leading-tight text-text-primary">{value}</p>
      <p className="mt-0.5 text-[11px] text-text-tertiary">{label}</p>
    </div>
  );
}

export function ActivityRow({ item }: { item: ActivityItem }) {
  return (
    <div className="flex items-center gap-3 px-4 py-3.5">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface-2">
        <Activity className="h-4 w-4 text-text-tertiary" strokeWidth={1.6} aria-hidden />
      </span>
      <p className="min-w-0 flex-1 truncate text-[14px] text-text-primary">{item.summary}</p>
      <span className="shrink-0 text-[12px] text-text-tertiary nums">
        {item.timestamp
          ? new Date(item.timestamp).toLocaleTimeString("ru-RU", {
              hour: "2-digit",
              minute: "2-digit",
            })
          : ""}
      </span>
    </div>
  );
}
