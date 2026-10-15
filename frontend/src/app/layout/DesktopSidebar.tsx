import {
  BellRing,
  Bot,
  CreditCard,
  Filter,
  FolderKanban,
  Home,
  Images,
  Info,
  LayoutGrid,
  MessagesSquare,
  Moon,
  ScrollText,
  Shield,
  SlidersHorizontal,
  Sun,
  Users,
  UserRound,
  Wifi,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useIsAdmin } from "../../shared/admin";
import { PlanBadge } from "../../shared/PlanBadge";
import { useUiStore } from "../../shared/store";

/* Навигация десктопа (lg+): вместо нижней капсулы — постоянная боковая
   панель со ВСЕМИ разделами сразу (на телефоне часть спрятана в «Ещё»). */

interface Item {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
  // Доп. префиксы пути, на которых пункт тоже подсвечен.
  alsoActiveOn?: string[];
}

const MAIN: Item[] = [
  { to: "/", label: "Главная", icon: Home, end: true },
  { to: "/accounts", label: "Аккаунты", icon: Users },
  { to: "/tasks", label: "Нейрокомментинг", icon: LayoutGrid, alsoActiveOn: ["/modules/commenting"] },
  { to: "/modules/shilling", label: "НейроШиллинг", icon: MessagesSquare, alsoActiveOn: ["/modules/shilling"] },
  { to: "/modules/priming", label: "Прайминг", icon: BellRing, alsoActiveOn: ["/modules/priming"] },
  { to: "/modules/parsing", label: "Парсинг", icon: Filter, alsoActiveOn: ["/modules/parsing"] },
];

const TOOLS: Item[] = [
  { to: "/more/autopilot", label: "Автопилот", icon: Bot },
  { to: "/more/projects", label: "Группы аккаунтов", icon: FolderKanban },
  { to: "/more/personas", label: "Персоны", icon: UserRound },
  { to: "/more/profile-assets", label: "Пул оформления", icon: Images },
  { to: "/more/proxies", label: "Прокси", icon: Wifi },
  { to: "/more/audit", label: "Аудит", icon: ScrollText },
];

const SYSTEM: Item[] = [
  { to: "/billing", label: "Тариф и лимиты", icon: CreditCard },
  { to: "/more/settings", label: "Настройки", icon: SlidersHorizontal },
  { to: "/more/about", label: "О приложении", icon: Info },
];

export function DesktopSidebar() {
  const navigate = useNavigate();
  const { isAdmin } = useIsAdmin();
  const theme = useUiStore((s) => s.theme);
  const toggleTheme = useUiStore((s) => s.toggleTheme);

  return (
    <aside className="sticky top-0 hidden h-screen w-[260px] shrink-0 flex-col border-r border-hairline bg-bg-elevated lg:flex">
      <div className="px-6 pb-4 pt-6">
        <p className="text-[20px] font-bold tracking-tight text-text-primary">Neuro</p>
        <p className="text-[12px] text-text-tertiary">Управление аккаунтами</p>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 pb-4 [scrollbar-width:thin]">
        <Group items={MAIN} />
        <GroupTitle>Инструменты</GroupTitle>
        <Group items={TOOLS} />
        <GroupTitle>Система</GroupTitle>
        <Group
          items={isAdmin ? [...SYSTEM, { to: "/admin", label: "Админ", icon: Shield }] : SYSTEM}
        />
      </nav>

      <div className="flex items-center justify-between gap-2 border-t border-hairline px-4 py-4">
        <button
          type="button"
          onClick={() => navigate("/billing")}
          aria-label="Ваш тариф"
          className="rounded-pill transition-opacity hover:opacity-80"
        >
          <PlanBadge size="md" />
        </button>
        <ThemeToggle theme={theme} onToggle={toggleTheme} />
      </div>
    </aside>
  );
}

/* Переключатель темы — ползунок в стиле приложения: pill-трек с hairline,
   скользящий кружок и иконки луны/солнца по краям. Светлая тема — кружок
   справа (солнце), тёмная — слева (луна). */
function ThemeToggle({
  theme,
  onToggle,
}: {
  theme: "light" | "dark";
  onToggle: () => void;
}) {
  const isLight = theme === "light";
  return (
    <button
      type="button"
      role="switch"
      aria-checked={isLight}
      onClick={onToggle}
      aria-label={isLight ? "Включить тёмную тему" : "Включить светлую тему"}
      className="relative inline-flex h-9 w-16 shrink-0 items-center rounded-pill border border-hairline bg-surface-1 px-1 transition-colors hover:border-strong"
    >
      {/* Иконки по краям трека — подсказка направления. */}
      <span className="pointer-events-none absolute inset-0 flex items-center justify-between px-2 text-text-tertiary">
        <Moon className="h-3.5 w-3.5" strokeWidth={1.8} aria-hidden />
        <Sun className="h-3.5 w-3.5" strokeWidth={1.8} aria-hidden />
      </span>
      {/* Кружок с активной иконкой. Позицию задаём флексом (ml-auto), а не
         transform — так надёжнее (reduced-motion/эмуляция не ломает сдвиг). */}
      <span
        className={[
          "relative z-10 flex h-7 w-7 items-center justify-center rounded-full bg-surface-2 text-text-primary shadow-sm",
          isLight ? "ml-auto" : "",
        ].join(" ")}
        style={{ boxShadow: "0 0 0 1px var(--surface-border-strong) inset" }}
      >
        {isLight ? (
          <Sun className="h-4 w-4" strokeWidth={2} aria-hidden />
        ) : (
          <Moon className="h-4 w-4" strokeWidth={2} aria-hidden />
        )}
      </span>
    </button>
  );
}

function GroupTitle({ children }: { children: string }) {
  return (
    <p className="px-3 pb-1.5 pt-5 text-[11px] font-semibold uppercase tracking-wide text-text-tertiary">
      {children}
    </p>
  );
}

function Group({ items }: { items: Item[] }) {
  const { pathname } = useLocation();
  return (
    <ul className="flex flex-col gap-0.5">
      {items.map(({ to, label, icon: Icon, end, alsoActiveOn }) => (
        <li key={to}>
          <NavLink
            to={to}
            end={end}
            className={({ isActive }) =>
              [
                "flex h-10 items-center gap-3 rounded-chip px-3 text-[14px] font-medium transition-colors",
                isActive || alsoActiveOn?.some((p) => pathname.startsWith(p))
                  ? "bg-surface-2 text-text-primary"
                  : "text-text-secondary hover:bg-surface-1 hover:text-text-primary",
              ].join(" ")
            }
          >
            <Icon className="h-[18px] w-[18px] shrink-0" strokeWidth={1.8} aria-hidden />
            <span className="truncate">{label}</span>
          </NavLink>
        </li>
      ))}
    </ul>
  );
}
