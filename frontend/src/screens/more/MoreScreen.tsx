import {
  Bot,
  CreditCard,
  FolderKanban,
  Images,
  Info,
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

interface Entry {
  to: string;
  icon: LucideIcon;
  label: string;
}

const TOOLS: Entry[] = [
  { to: "/more/projects", icon: FolderKanban, label: "Группы аккаунтов" },
  { to: "/more/personas", icon: UserRound, label: "Персоны" },
  { to: "/more/profile-assets", icon: Images, label: "Пул оформления" },
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

      <AutopilotHero />

      <SectionTitle>Инструменты</SectionTitle>
      <div className="card mb-8 overflow-hidden p-0">
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

function AutopilotHero() {
  return (
    <Link
      to="/more/autopilot"
      className="card-hero mb-8 flex items-start gap-5 p-6 active:opacity-90"
    >
      <div className="min-w-0 flex-1">
        <div className="text-[20px] font-bold leading-tight text-text-primary">
          Автопилот
        </div>
        <p className="mt-2 text-[14px] leading-relaxed text-text-secondary">
          Автоматизируйте прогрев, ротацию и мониторинг аккаунтов
        </p>
        <span className="mt-5 inline-flex items-center rounded-pill bg-accent px-5 py-2.5 text-[14px] font-semibold text-accent-on">
          Настроить
        </span>
      </div>
      <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-surface-2 text-text-primary">
        <Bot className="h-7 w-7" strokeWidth={1.4} aria-hidden />
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
