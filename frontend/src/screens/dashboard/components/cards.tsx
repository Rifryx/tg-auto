import {
  Activity,
  AlertTriangle,
  Ban,
  ChevronRight,
  KeyRound,
  MailX,
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
  // Целевые каналы нейрокомментинга (E3.2).
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

/* Карточка алерта: левая цветная полоса 4px по severity (§7), иконка, аккаунт. */
export function AlertCard({ alert, count = 1 }: { alert: Alert; count?: number }) {
  const Icon = EVENT_ICON[alert.event_type] ?? AlertTriangle;
  const bar = alert.severity === "critical" ? "bg-status-critical" : "bg-status-warning";
  const tone = alert.severity === "critical" ? "text-status-critical" : "text-status-warning";
  // Алерты каналов ведут в кампанию, где их можно разобрать; остальные — в аккаунт.
  const campaignId = alert.event_type.startsWith("commenting.") ? alert.meta?.campaign_id : null;
  const channel = typeof alert.meta?.channel === "string" ? alert.meta.channel : null;
  const who = alert.phone ? maskPhone(alert.phone) : `Аккаунт #${alert.account_id}`;
  return (
    <Link
      to={campaignId ? `/modules/commenting/campaigns/${campaignId}` : `/accounts/${alert.account_id}`}
      className="card relative flex items-center gap-3 overflow-hidden py-3 pl-5 pr-4 active:bg-surface-2"
    >
      <span className={`absolute inset-y-0 left-0 w-1 ${bar}`} aria-hidden />
      <Icon className={`h-5 w-5 shrink-0 ${tone}`} strokeWidth={1.8} aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[14px] font-medium text-text-primary">
          {EVENT_LABEL[alert.event_type] ?? alert.event_type}
        </p>
        <p className="truncate text-[12px] text-text-tertiary nums">
          {channel ? `${who} · ${channel}` : who}
        </p>
      </div>
      {count > 1 && (
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[12px] font-semibold tabular-nums ${tone}`}
          style={{ background: "color-mix(in srgb, currentColor 16%, transparent)" }}>
          ×{count}
        </span>
      )}
      <ChevronRight className="h-4 w-4 text-text-tertiary" strokeWidth={1.8} aria-hidden />
    </Link>
  );
}

/* KPI-карточка стадии: крупный count, status-dot цвета стадии. */
export function StageCard({ status, count }: { status: AccountStatus; count: number }) {
  return (
    <Link
      to={`/accounts?status=${status}`}
      className="card flex w-[128px] shrink-0 flex-col justify-between p-4 active:bg-surface-2"
    >
      <div className="mb-4 flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${statusDotClass(status)}`} aria-hidden />
        <span className="text-[13px] text-text-secondary">{STATUS_LABEL[status]}</span>
      </div>
      <span className="nums text-[30px] font-bold leading-none text-text-primary">{count}</span>
    </Link>
  );
}

/* Компактная карточка модуля. */
export function ModuleCard({ module }: { module: ModuleSummary }) {
  return (
    <Link
      to="/tasks"
      className="card flex flex-col gap-3 p-4 active:bg-surface-2"
    >
      <div className="flex items-center gap-2">
        <MessagesSquare className="h-5 w-5 text-text-secondary" strokeWidth={1.6} aria-hidden />
        <span className="text-[15px] font-semibold text-text-primary">
          {module.module === "commenting" ? "Комментирование" : module.module}
        </span>
      </div>
      <div className="flex gap-4">
        <Metric label="Кампаний" value={module.instances} />
        <Metric label="В работе" value={module.active_now} />
        <Metric label="Сегодня" value={module.today_actions} />
      </div>
    </Link>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <p className="nums text-[19px] font-bold leading-tight text-text-primary">{value}</p>
      <p className="text-[11px] text-text-tertiary">{label}</p>
    </div>
  );
}

/* Строка ленты активности (переиспользуется в /more/audit). */
export function ActivityRow({ item }: { item: ActivityItem }) {
  return (
    <div className="flex items-center gap-3 py-2.5">
      <Activity className="h-4 w-4 shrink-0 text-text-tertiary" strokeWidth={1.6} aria-hidden />
      <p className="min-w-0 flex-1 truncate text-[14px] text-text-primary">{item.summary}</p>
      <span className="shrink-0 text-[12px] text-text-tertiary">
        {item.timestamp ? new Date(item.timestamp).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }) : ""}
      </span>
    </div>
  );
}
