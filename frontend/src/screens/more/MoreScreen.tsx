import {
  Bot,
  CreditCard,
  FolderKanban,
  Info,
  ScrollText,
  Shield,
  SlidersHorizontal,
  UserRound,
  Wifi,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { useIsAdmin } from "../../shared/admin";
import { MoreRow } from "./components/ui";

/* Служебные разделы: инструменты и системные ссылки.
   Модули кампаний (Нейрокомментинг, НейроШиллинг, Прайминг, Парсинг)
   живут в отдельном табе «Сервисы» (/services) — чтобы в «Ещё» были
   только инфраструктурные настройки. */

interface Entry {
  to: string;
  icon: LucideIcon;
  label: string;
}

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
