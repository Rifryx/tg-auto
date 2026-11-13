import {
  Bot,
  BellRing,
  ChevronRight,
  Filter,
  LayoutGrid,
  MessagesSquare,
  ScrollText,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { useActiveParsingJobs } from "../../modules/parsing/useActiveParsingJobs";

interface Service {
  to: string;
  icon: LucideIcon;
  label: string;
  hint: string;
  /** Тихая метка справа от названия (например, «Новое»). */
  tag?: string;
  /** Зацикленный индикатор, пока фоновая задача идёт (сейчас — парсинг). */
  runningIndicator?: boolean;
}

// Модули продвижения — все в одной группе и одинаковыми строками, чтобы ни один
// не «висел» отдельным баннером без причины (прайминг раньше был hero-карточкой).
const PROMOTION: Service[] = [
  { to: "/tasks", icon: LayoutGrid, label: "Нейрокомментинг", hint: "Кампании и комментарии под постами" },
  { to: "/modules/shilling", icon: MessagesSquare, label: "НейроШиллинг", hint: "Сценарии посевов в чатах" },
  { to: "/modules/priming", icon: BellRing, label: "Прайминг", hint: "Касания через системные события, без сообщений", tag: "Новое" },
];

const DATA: Service[] = [
  {
    to: "/modules/parsing",
    icon: Filter,
    label: "Парсинг",
    hint: "Списки целей для прайминга и шиллинга",
    runningIndicator: true,
  },
];

const AUTOMATION: Service[] = [
  { to: "/more/autopilot", icon: Bot, label: "Автопилот", hint: "Прогрев, ротация и мониторинг на автомате" },
  { to: "/more/audit", icon: ScrollText, label: "Аудит активности", hint: "История операций по аккаунтам" },
];

export function ServicesScreen() {
  return (
    <>
      <ScreenHeader title="Сервисы" />

      <ServiceGroup title="Продвижение" items={PROMOTION} />
      <ServiceGroup title="Данные" items={DATA} />
      <ServiceGroup title="Автоматизация" items={AUTOMATION} />
    </>
  );
}

function ServiceGroup({ title, items }: { title: string; items: Service[] }) {
  return (
    <section className="mb-8">
      <h2 className="section-title mb-3">{title}</h2>
      <div className="card overflow-hidden p-0">
        {items.map((s, i) => (
          <div key={s.to} className={i > 0 ? "border-t border-hairline" : ""}>
            <ServiceRow {...s} />
          </div>
        ))}
      </div>
    </section>
  );
}

function ServiceRow({ to, icon: Icon, label, hint, tag, runningIndicator }: Service) {
  const parsingActive = useActiveParsingJobs();
  const showBar = runningIndicator && parsingActive;
  return (
    <Link to={to} className="flex items-center gap-4 px-4 py-4 transition-colors active:bg-surface-2">
      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-surface-2 text-text-secondary">
        <Icon className="h-5 w-5" strokeWidth={1.7} aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-[15px] font-semibold leading-tight text-text-primary">
            {label}
          </span>
          {tag && (
            <span className="shrink-0 rounded-pill border border-hairline px-2 py-0.5 text-[11px] font-medium text-text-tertiary">
              {tag}
            </span>
          )}
        </div>
        <div className="mt-0.5 truncate text-[13px] text-text-tertiary">
          {showBar ? "Парсинг выполняется…" : hint}
        </div>
        {showBar && (
          <div className="mt-1.5 h-[2px] w-24 overflow-hidden rounded-full bg-surface-2">
            <div className="h-full w-1/3 animate-nav-running-bar rounded-full bg-accent" />
          </div>
        )}
      </div>
      <ChevronRight className="h-4 w-4 shrink-0 text-text-tertiary" strokeWidth={1.8} aria-hidden />
    </Link>
  );
}
