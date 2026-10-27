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
      className="card relative flex w-full flex-col justify-between gap-2 overflow-hidden p-3.5 active:bg-surface-2"
      style={{ minHeight: 92 }}
    >
      <span className={`absolute inset-y-0 left-0 w-[3px] ${barClass}`} aria-hidden />
      <div className="flex items-center gap-1.5 pl-1">
        <span className={`h-2 w-2 shrink-0 rounded-full ${statusDotClass(status)}`} aria-hidden />
        <span className="truncate text-[12px] text-text-secondary">
          {STATUS_LABEL[status]}
        </span>
      </div>
      <span className="nums pl-1 text-[28px] font-bold leading-none text-text-primary">
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

// Русские подписи типов действий — на случай, если сервер не прислал detail
// (старый кэш/запись): интерфейс не должен показывать английские action_type.
const ACTION_RU: Record<string, string> = {
  subscribe_channel: "Подписка на канал",
  read_history: "Чтение истории",
  reaction: "Реакция на пост",
  view_media: "Просмотр медиа",
  join_group: "Вступление в группу",
  idle_online: "Был онлайн",
  update_profile: "Обновление профиля",
  interact_with_peer: "Взаимодействие",
  comment: "Комментарий",
};
const STATUS_RU: Record<string, string> = {
  done: "выполнено",
  failed: "ошибка",
  skipped: "пропущено",
};

export function ActivityRow({ item, tz }: { item: ActivityItem; tz?: string }) {
  const who =
    item.display_name?.trim() || (item.phone ? maskPhone(item.phone) : `Аккаунт #${item.account_id}`);
  // Основная строка — развёрнутая деталь (что, где, какая реакция и т.п.).
  // Если detail нет — собираем русскую подпись из action_type/status, чтобы
  // не показывать английское «read_history (done)».
  const fallback = item.action_type
    ? `${ACTION_RU[item.action_type] ?? item.action_type}${
        item.status && item.status !== "done" ? ` · ${STATUS_RU[item.status] ?? item.status}` : ""
      }`
    : item.summary;
  const primary = item.detail?.trim() || fallback;
  const failed = item.status === "failed";
  return (
    <div className="flex items-center gap-3 px-4 py-3.5">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface-2">
        <Activity
          className={`h-4 w-4 ${failed ? "text-status-critical" : "text-text-tertiary"}`}
          strokeWidth={1.6}
          aria-hidden
        />
      </span>
      <div className="min-w-0 flex-1">
        <p className={`truncate text-[14px] ${failed ? "text-status-critical" : "text-text-primary"}`}>
          {primary}
        </p>
        <p className="truncate text-[12px] text-text-tertiary">{who}</p>
      </div>
      <span className="shrink-0 text-right text-[12px] text-text-tertiary nums">
        {item.timestamp ? formatActivityWhen(item.timestamp, tz) : ""}
      </span>
    </div>
  );
}

/** «14:51» если сегодня, «вчера 14:51» если вчера, иначе «26.10 14:51»
 *  — пользователь просил показывать не только часы, но и дату. */
function formatActivityWhen(ts: string, tz?: string): string {
  const date = new Date(ts);
  const timeOpts: Intl.DateTimeFormatOptions = {
    hour: "2-digit",
    minute: "2-digit",
    ...(tz ? { timeZone: tz } : {}),
  };
  const time = date.toLocaleTimeString("ru-RU", timeOpts);
  const sameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate();
  const now = new Date();
  if (sameDay(date, now)) return time;
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (sameDay(date, yesterday)) return `вчера ${time}`;
  const dateOpts: Intl.DateTimeFormatOptions = {
    day: "2-digit",
    month: "2-digit",
    ...(tz ? { timeZone: tz } : {}),
  };
  return `${date.toLocaleDateString("ru-RU", dateOpts)} ${time}`;
}
