import {
  Activity,
  AlertTriangle,
  Ban,
  ChevronRight,
  Flame,
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
import type { Alert, ActivityItem, ModuleSummary, TrendPoint } from "../api";

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
      <span className="nums pl-1 text-[28px] font-semibold leading-none text-text-primary">
        {count}
      </span>
    </Link>
  );
}

const MODULE_META: Record<string, { label: string; icon: LucideIcon; to: string }> = {
  commenting: { label: "Нейрокомментинг", icon: MessagesSquare, to: "/modules/commenting" },
  shilling: { label: "Нейрошиллинг", icon: Megaphone, to: "/modules/shilling" },
  priming: { label: "Прайминг", icon: Flame, to: "/modules/priming" },
};

// Плоская карточка модуля (без градиентов — пользователь просил убрать
// «нейрослоп»): иконка-чип, название, активная/пауза-метка и три метрики с
// hairline-разделителями. Сидит в адаптивной сетке (1 кол. на телефоне, 3 на ПК).
export function ModuleCard({ module }: { module: ModuleSummary }) {
  const meta = MODULE_META[module.module];
  const Icon = meta?.icon ?? MessagesSquare;
  const live = module.active_now > 0;
  return (
    <Link
      to={meta?.to ?? "/tasks"}
      className="card flex flex-col p-4 transition-colors active:bg-surface-2"
    >
      <div className="flex items-center gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-chip bg-surface-2 text-text-primary">
          <Icon className="h-[18px] w-[18px]" strokeWidth={1.7} aria-hidden />
        </span>
        <span className="min-w-0 flex-1 truncate text-[15px] font-semibold text-text-primary">
          {meta?.label ?? module.module}
        </span>
        {live ? (
          <span className="flex shrink-0 items-center gap-1.5 text-[11px] font-medium text-status-active">
            <span className="h-1.5 w-1.5 rounded-full bg-status-active" aria-hidden />
            В работе
          </span>
        ) : (
          <ChevronRight className="h-4 w-4 shrink-0 text-text-tertiary" strokeWidth={1.8} aria-hidden />
        )}
      </div>
      <div className="mt-4 grid grid-cols-3 divide-x divide-hairline">
        <Metric label="Кампаний" value={module.instances} />
        <Metric label="В работе" value={module.active_now} align="center" />
        <Metric label="Сегодня" value={module.today_actions} align="right" />
      </div>
    </Link>
  );
}

function Metric({
  label,
  value,
  align = "left",
}: {
  label: string;
  value: number;
  align?: "left" | "center" | "right";
}) {
  const box =
    align === "center" ? "items-center px-2" : align === "right" ? "items-end pl-2" : "items-start pr-2";
  return (
    <div className={`flex flex-col ${box}`}>
      <p className="nums text-[19px] font-semibold leading-tight text-text-primary">{value}</p>
      <p className="mt-0.5 text-[11px] text-text-tertiary">{label}</p>
    </div>
  );
}

// --- KPI-плитка -------------------------------------------------------------
// Плоская карточка с крупным числом и подписью. tone подсвечивает число, когда
// значение требует внимания (ошибки/пауза), иначе — нейтральный основной цвет.
export function KpiTile({
  label,
  value,
  tone = "neutral",
  sub,
  to,
}: {
  label: string;
  value: number;
  tone?: "neutral" | "warning" | "critical" | "active";
  sub?: string | null;
  to?: string;
}) {
  // Тон числа подсвечивает только то, что требует внимания (ошибки) и только
  // когда значение > 0; «active» держим нейтральным, чтобы не было зелёного
  // декора ради декора (бриф: цвет — лишь для статусов).
  const toneClass =
    value > 0 && tone === "critical"
      ? "text-status-critical"
      : value > 0 && tone === "warning"
        ? "text-status-warning"
        : "text-text-primary";
  const inner = (
    <>
      <p className={`nums text-[27px] font-semibold leading-none ${toneClass}`}>{value}</p>
      <div className="mt-2">
        <p className="text-[12px] leading-tight text-text-secondary">{label}</p>
        {sub ? <p className="mt-0.5 text-[11px] leading-tight text-text-tertiary">{sub}</p> : null}
      </div>
    </>
  );
  const cls = "card flex min-h-[86px] flex-col justify-between gap-2 p-4";
  if (to) {
    return (
      <Link to={to} className={`${cls} transition-colors active:bg-surface-2`}>
        {inner}
      </Link>
    );
  }
  return <div className={cls}>{inner}</div>;
}

// --- 7-дневный тренд действий ----------------------------------------------
// Главный «момент» экрана: тренд — это линия (не столбцы). Плавная линия-область
// на приглушённой сетке, один акцент (сегодня), мру-подписи дней. Рисуем SVG
// руками, без библиотек; stroke не тянется (vector-effect), точка «сегодня» —
// оверлеем в процентах, чтобы не искажалась при растяжении по ширине.
const WEEKDAY_RU = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];

const TREND_H = 200; // высота поля графика, px (токены: 280–360 с заголовком)
const PAD_T = 14; // отступ сверху, чтобы пик не упирался в край
const PAD_B = 10;

export function TrendChart({ points }: { points: TrendPoint[] }) {
  const total = points.reduce((a, p) => a + p.actions, 0);
  const max = Math.max(1, ...points.map((p) => p.actions));
  const todayIso = new Date().toISOString().slice(0, 10);
  const avg = Math.round(total / Math.max(1, points.length));

  const n = points.length;
  const plotH = TREND_H - PAD_T - PAD_B;
  // Координаты в процентах по X (0..100) и в пикселях по Y (0..TREND_H).
  const pts = points.map((p, i) => ({
    x: n > 1 ? (i / (n - 1)) * 100 : 50,
    y: PAD_T + (1 - p.actions / max) * plotH,
    p,
  }));
  const linePath = pts.map((pt, i) => `${i === 0 ? "M" : "L"} ${pt.x} ${pt.y}`).join(" ");
  const areaPath = `${linePath} L 100 ${TREND_H} L 0 ${TREND_H} Z`;
  const last = pts[pts.length - 1];

  return (
    <div className="card p-5">
      <div className="mb-4 flex items-end justify-between">
        <div>
          <p className="nums text-[28px] font-semibold leading-none text-text-primary">{total}</p>
          <p className="mt-1.5 text-[12px] text-text-tertiary">действий за 7 дней</p>
        </div>
        <span className="nums text-[12px] text-text-tertiary">≈ {avg} в день</span>
      </div>

      {total === 0 ? (
        <div
          className="flex items-center justify-center text-[13px] text-text-tertiary"
          style={{ height: TREND_H }}
        >
          Пока нет действий за неделю
        </div>
      ) : (
        <>
          <div className="relative" style={{ height: TREND_H }}>
            <svg
              viewBox={`0 0 100 ${TREND_H}`}
              preserveAspectRatio="none"
              className="absolute inset-0 h-full w-full"
              aria-hidden
            >
              {/* Приглушённая сетка: три линии (низ/середина/верх). */}
              {[PAD_T, PAD_T + plotH / 2, TREND_H - PAD_B].map((y, i) => (
                <line
                  key={i}
                  x1="0"
                  x2="100"
                  y1={y}
                  y2={y}
                  stroke="var(--surface-border)"
                  strokeWidth="1"
                  vectorEffect="non-scaling-stroke"
                />
              ))}
              <defs>
                <linearGradient id="trend-fill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--text-primary)" stopOpacity="0.16" />
                  <stop offset="100%" stopColor="var(--text-primary)" stopOpacity="0" />
                </linearGradient>
              </defs>
              <path d={areaPath} fill="url(#trend-fill)" />
              <path
                d={linePath}
                fill="none"
                stroke="var(--text-primary)"
                strokeWidth="2"
                strokeLinejoin="round"
                strokeLinecap="round"
                vectorEffect="non-scaling-stroke"
              />
            </svg>
            {/* Точка «сегодня» — оверлеем в %, чтобы круг не превращался в эллипс. */}
            <span
              className="absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-text-primary ring-4 ring-surface-1"
              style={{ left: `${last.x}%`, top: `${last.y}px` }}
              aria-hidden
            />
          </div>
          <div className="mt-2.5 flex">
            {points.map((p) => {
              const isToday = p.date === todayIso;
              const wd = WEEKDAY_RU[new Date(`${p.date}T00:00:00Z`).getUTCDay()];
              return (
                <span
                  key={p.date}
                  className={`nums flex-1 text-center text-[10.5px] leading-none ${
                    isToday ? "font-medium text-text-secondary" : "text-text-tertiary"
                  }`}
                >
                  {isToday ? "сег." : wd}
                </span>
              );
            })}
          </div>
        </>
      )}
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
