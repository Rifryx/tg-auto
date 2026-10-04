import { BellRing, ChevronRight, Filter, LayoutGrid, MessagesSquare, Sparkles } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";

interface Service {
  to: string;
  icon: LucideIcon;
  label: string;
  hint: string;
}

const CAMPAIGNS: Service[] = [
  {
    to: "/tasks",
    icon: LayoutGrid,
    label: "Нейрокомментинг",
    hint: "Кампании и комментарии",
  },
  {
    to: "/modules/shilling",
    icon: MessagesSquare,
    label: "НейроШиллинг",
    hint: "Сценарии посевов",
  },
];

const DATA: Service[] = [
  {
    to: "/modules/parsing",
    icon: Filter,
    label: "Парсинг",
    hint: "Готовые списки целей для прайминга и шиллинга",
  },
];

export function ServicesScreen() {
  return (
    <>
      <ScreenHeader title="Сервисы" />

      <PrimingHero />

      <SectionTitle>Кампании</SectionTitle>
      <div className="card mb-8 overflow-hidden p-0">
        {CAMPAIGNS.map((s, i) => (
          <div key={s.to} className={i > 0 ? "border-t border-hairline" : ""}>
            <ServiceRow {...s} />
          </div>
        ))}
      </div>

      <SectionTitle>Данные</SectionTitle>
      <div className="card mb-8 overflow-hidden p-0">
        {DATA.map((s) => (
          <ServiceRow key={s.to} {...s} />
        ))}
      </div>

      <div className="card overflow-hidden p-0">
        <QuickLink to="/more/audit" label="Аудит активности" />
        <div className="border-t border-hairline" />
        <QuickLink to="/more/autopilot" label="Автопилот" />
      </div>
    </>
  );
}

function PrimingHero() {
  return (
    <Link
      to="/modules/priming"
      className="card-hero mb-8 flex items-start gap-5 p-6 active:opacity-90"
    >
      <div className="min-w-0 flex-1">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span className="text-[20px] font-bold leading-tight text-text-primary">
            Прайминг
          </span>
          <span className="inline-flex items-center gap-1 rounded-pill bg-accent px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-accent-on">
            <Sparkles className="h-3 w-3" strokeWidth={2} aria-hidden />
            Новое
          </span>
        </div>
        <p className="text-[14px] leading-relaxed text-text-secondary">
          Push через системные события — без сообщений в чате
        </p>
        <span className="mt-5 inline-flex items-center rounded-pill bg-accent px-5 py-2.5 text-[14px] font-semibold text-accent-on">
          Попробовать
        </span>
      </div>
      <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-surface-2 text-text-primary">
        <BellRing className="h-8 w-8" strokeWidth={1.4} aria-hidden />
      </span>
    </Link>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2
      className="mb-4 text-[22px] font-bold leading-tight text-text-primary"
      style={{ letterSpacing: "-0.01em" }}
    >
      {children}
    </h2>
  );
}

function ServiceRow({ to, icon: Icon, label, hint }: Service) {
  return (
    <Link to={to} className="flex items-center gap-4 px-4 py-4 active:bg-surface-2">
      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-surface-2 text-text-primary">
        <Icon className="h-5 w-5" strokeWidth={1.7} aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[15px] font-semibold leading-tight text-text-primary">{label}</div>
        <div className="mt-0.5 truncate text-[13px] text-text-tertiary">{hint}</div>
      </div>
      <ChevronRight className="h-4 w-4 shrink-0 text-text-tertiary" strokeWidth={1.8} aria-hidden />
    </Link>
  );
}

function QuickLink({ to, label }: { to: string; label: string }) {
  return (
    <Link to={to} className="flex items-center gap-3 px-4 py-3.5 active:bg-surface-2">
      <span className="flex-1 text-[15px] text-text-primary">{label}</span>
      <ChevronRight className="h-4 w-4 text-text-tertiary" strokeWidth={1.8} aria-hidden />
    </Link>
  );
}
