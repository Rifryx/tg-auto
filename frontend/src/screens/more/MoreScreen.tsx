import {
  BellRing,
  Bot,
  CreditCard,
  Filter,
  FolderKanban,
  Info,
  LayoutGrid,
  MessagesSquare,
  ScrollText,
  Shield,
  SlidersHorizontal,
  UserRound,
  Wifi,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { useIsAdmin } from "../../shared/admin";
import { MoreRow } from "./components/ui";

/* На мобильном навбаре всего 5 слотов (Главная / Аккаунты / Коммент /
   Шиллинг / Ещё). Все остальные разделы (Прайминг, Парсинг, инструменты,
   биллинг, админка) живут здесь, сгруппированы как в DesktopSidebar.

   Структура: заметные плитки сверху — модули кампаний (их чаще
   открывают), ниже — служебные инструменты и системные ссылки. */

interface Entry {
  to: string;
  icon: LucideIcon;
  label: string;
  hint?: string;
}

const MODULES: Entry[] = [
  { to: "/tasks", icon: LayoutGrid, label: "Нейрокомментинг", hint: "Кампании и комментарии" },
  { to: "/modules/shilling", icon: MessagesSquare, label: "НейроШиллинг", hint: "Сценарии посевов" },
  { to: "/modules/priming", icon: BellRing, label: "Прайминг", hint: "Push через системные события" },
  { to: "/modules/parsing", icon: Filter, label: "Парсинг", hint: "Готовые списки целей" },
];

const TOOLS: Entry[] = [
  { to: "/more/autopilot", icon: Bot, label: "Автопилот" },
  { to: "/more/projects", icon: FolderKanban, label: "Группы аккаунтов" },
  { to: "/more/personas", icon: UserRound, label: "Персоны" },
  { to: "/more/proxies", icon: Wifi, label: "Прокси" },
  { to: "/more/audit", icon: ScrollText, label: "Аудит" },
];

const SYSTEM: Entry[] = [
  { to: "/billing", icon: CreditCard, label: "Тариф и лимиты" },
  { to: "/more/settings", icon: SlidersHorizontal, label: "Настройки" },
  { to: "/more/about", icon: Info, label: "О приложении" },
];

export function MoreScreen() {
  const { isAdmin } = useIsAdmin();
  const system: Entry[] = isAdmin
    ? [{ to: "/admin", icon: Shield, label: "Админ" }, ...SYSTEM]
    : SYSTEM;

  return (
    <>
      <ScreenHeader title="Ещё" />

      {/* Модули — крупные 2-колоночные плитки, чтобы попадали пальцем */}
      <SectionTitle>Модули</SectionTitle>
      <div className="mb-6 grid grid-cols-2 gap-2.5">
        {MODULES.map((m) => (
          <ModuleTile key={m.to} {...m} />
        ))}
      </div>

      <SectionTitle>Инструменты</SectionTitle>
      <div className="card mb-6 overflow-hidden p-0">
        {TOOLS.map((it, i) => (
          <div key={it.to} className={i > 0 ? "border-t border-hairline" : ""}>
            <MoreRow {...it} />
          </div>
        ))}
      </div>

      <SectionTitle>Система</SectionTitle>
      <div className="card overflow-hidden p-0">
        {system.map((it, i) => (
          <div key={it.to} className={i > 0 ? "border-t border-hairline" : ""}>
            <MoreRow {...it} />
          </div>
        ))}
      </div>
    </>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-2.5 px-1 text-[12px] font-semibold uppercase tracking-wide text-text-tertiary">
      {children}
    </h2>
  );
}

function ModuleTile({ to, icon: Icon, label, hint }: Entry) {
  return (
    <Link
      to={to}
      className="card flex min-h-[108px] flex-col justify-between gap-3 p-4 text-left active:bg-surface-2"
    >
      <span className="flex h-10 w-10 items-center justify-center rounded-pill bg-surface-2 text-text-primary">
        <Icon className="h-[20px] w-[20px]" strokeWidth={1.8} aria-hidden />
      </span>
      <div className="min-w-0">
        <div className="text-[14px] font-semibold leading-tight text-text-primary">
          {label}
        </div>
        {hint && (
          <div className="mt-0.5 line-clamp-2 text-[11px] leading-tight text-text-tertiary">
            {hint}
          </div>
        )}
      </div>
    </Link>
  );
}
