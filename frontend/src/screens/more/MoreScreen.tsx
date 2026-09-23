import {
  Bot,
  FolderKanban,
  Info,
  ScrollText,
  SlidersHorizontal,
  Users,
  Wifi,
} from "lucide-react";
import { ScreenHeader } from "../../app/layout/AppLayout";
import { MoreRow } from "./components/ui";

const ITEMS = [
  { to: "/more/autopilot", icon: Bot, label: "Автопилот" },
  { to: "/more/projects", icon: FolderKanban, label: "Группы аккаунтов" },
  { to: "/more/personas", icon: Users, label: "Персоны" },
  { to: "/more/proxies", icon: Wifi, label: "Прокси" },
  { to: "/more/audit", icon: ScrollText, label: "Аудит" },
  { to: "/more/settings", icon: SlidersHorizontal, label: "Настройки" },
  { to: "/more/about", icon: Info, label: "О приложении" },
];

export function MoreScreen() {
  return (
    <>
      <ScreenHeader title="Ещё" />
      <div className="card overflow-hidden p-0">
        {ITEMS.map((it, i) => (
          <div key={it.to} className={i > 0 ? "border-t border-hairline" : ""}>
            <MoreRow {...it} />
          </div>
        ))}
      </div>
    </>
  );
}
