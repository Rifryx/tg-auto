import { Home, LayoutGrid, MoreHorizontal, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { NavLink } from "react-router-dom";
import { hapticSelection } from "../../shared/tg";

/* Капсульный плавающий нижний навбар (§5 брифа):
   - тёмная «таблетка» (surface-1 + hairline), НЕ full-width таббар;
   - плавает над контентом с отступом от краёв и от низа (safe-area);
   - активный таб — светлая подложка (accent) с тёмной иконкой/подписью
     (accent-on); неактивные — иконка + подпись text-secondary. */

interface Tab {
  to: string;
  label: string;
  icon: LucideIcon;
}

const TABS: Tab[] = [
  { to: "/", label: "Главная", icon: Home },
  { to: "/accounts", label: "Аккаунты", icon: Users },
  { to: "/tasks", label: "Задачи", icon: LayoutGrid },
  { to: "/more", label: "Ещё", icon: MoreHorizontal },
];

export function BottomNav() {
  return (
    <nav
      className="pointer-events-none fixed inset-x-0 bottom-0 z-40 flex justify-center"
      style={{ paddingBottom: "calc(env(safe-area-inset-bottom) + 12px)" }}
    >
      <div className="pointer-events-auto mx-4 flex h-16 items-center gap-1 rounded-pill border border-hairline bg-surface-1 px-2">
        {TABS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            onClick={() => hapticSelection()}
            className={({ isActive }) =>
              [
                "flex h-12 min-w-[64px] flex-col items-center justify-center gap-0.5 rounded-pill px-3 transition-colors",
                isActive
                  ? "bg-accent text-accent-on"
                  : "text-text-secondary active:text-text-primary",
              ].join(" ")
            }
          >
            {({ isActive }) => (
              <>
                <Icon
                  className="h-[22px] w-[22px]"
                  strokeWidth={isActive ? 2.2 : 1.8}
                  aria-hidden
                />
                <span className="text-[10px] font-medium leading-none">{label}</span>
              </>
            )}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
