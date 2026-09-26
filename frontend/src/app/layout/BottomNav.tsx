import { Grid2x2, Home, MoreHorizontal, Users, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { isModulePath, MODULES } from "../../shared/modules";
import { hapticSelection } from "../../shared/tg";

/* Капсульный плавающий нижний навбар (§5 брифа):
   - тёмная «таблетка» (surface-1 + hairline), НЕ full-width таббар;
   - плавает над контентом с отступом от краёв и от низа (safe-area);
   - активный таб — светлая подложка (accent) с тёмной иконкой/подписью.

   Модули-сервисы (комментинг, шиллинг, …) не занимают по табу каждый — они за
   одной кнопкой «Сервисы», открывающей селектор. Так навбар не растёт с числом
   модулей. */

interface Tab {
  to: string;
  label: string;
  icon: LucideIcon;
}

const CORE_LEFT: Tab[] = [
  { to: "/", label: "Главная", icon: Home },
  { to: "/accounts", label: "Аккаунты", icon: Users },
];
const CORE_RIGHT: Tab[] = [{ to: "/more", label: "Ещё", icon: MoreHorizontal }];

export function BottomNav() {
  const { pathname } = useLocation();
  const [servicesOpen, setServicesOpen] = useState(false);
  const servicesActive = isModulePath(pathname);

  return (
    <>
      <nav
        className="pointer-events-none fixed inset-x-0 bottom-0 z-40 flex justify-center"
        style={{ paddingBottom: "calc(env(safe-area-inset-bottom) + 12px)" }}
      >
        <div className="pointer-events-auto mx-3 flex h-16 items-center gap-0.5 rounded-pill border border-hairline bg-surface-1 px-1.5">
          {CORE_LEFT.map((t) => (
            <TabLink key={t.to} tab={t} />
          ))}

          {/* Селектор сервисов */}
          <button
            type="button"
            onClick={() => {
              hapticSelection();
              setServicesOpen(true);
            }}
            aria-label="Сервисы"
            className={[
              "flex h-12 min-w-[56px] flex-col items-center justify-center gap-0.5 rounded-pill px-2 transition-colors",
              servicesActive ? "bg-accent text-accent-on" : "text-text-secondary active:text-text-primary",
            ].join(" ")}
          >
            <Grid2x2 className="h-[22px] w-[22px]" strokeWidth={servicesActive ? 2.2 : 1.8} aria-hidden />
            <span className="text-[10px] font-medium leading-none">Сервисы</span>
          </button>

          {CORE_RIGHT.map((t) => (
            <TabLink key={t.to} tab={t} />
          ))}
        </div>
      </nav>

      {servicesOpen && <ServicesSheet onClose={() => setServicesOpen(false)} />}
    </>
  );
}

function TabLink({ tab }: { tab: Tab }) {
  const { to, label, icon: Icon } = tab;
  return (
    <NavLink
      to={to}
      end={to === "/"}
      onClick={() => hapticSelection()}
      className={({ isActive }) =>
        [
          "flex h-12 min-w-[56px] flex-col items-center justify-center gap-0.5 rounded-pill px-2 transition-colors",
          isActive ? "bg-accent text-accent-on" : "text-text-secondary active:text-text-primary",
        ].join(" ")
      }
    >
      {({ isActive }) => (
        <>
          <Icon className="h-[22px] w-[22px]" strokeWidth={isActive ? 2.2 : 1.8} aria-hidden />
          <span className="text-[10px] font-medium leading-none">{label}</span>
        </>
      )}
    </NavLink>
  );
}

/* Нижний лист выбора сервиса/модуля. */
function ServicesSheet({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const { pathname } = useLocation();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50"
      onClick={onClose}
    >
      <div
        className="w-full max-w-[440px] rounded-t-card border border-hairline bg-bg-elevated p-4"
        style={{ paddingBottom: "calc(env(safe-area-inset-bottom) + 16px)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-[16px] font-bold text-text-primary">Сервисы</h2>
          <button onClick={onClose} aria-label="Закрыть" className="text-text-tertiary active:text-text-primary">
            <X className="h-5 w-5" strokeWidth={1.8} aria-hidden />
          </button>
        </div>
        <div className="flex flex-col gap-2">
          {MODULES.map((m) => {
            const active = m.matchPrefixes.some((p) => pathname.startsWith(p));
            const Icon = m.icon;
            return (
              <button
                key={m.to}
                type="button"
                onClick={() => {
                  hapticSelection();
                  navigate(m.to);
                  onClose();
                }}
                className={[
                  "flex items-center gap-3 rounded-card border p-3 text-left transition-colors",
                  active ? "border-accent bg-surface-2" : "border-hairline bg-surface-1 active:bg-surface-2",
                ].join(" ")}
              >
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-2 text-text-primary">
                  <Icon className="h-5 w-5" strokeWidth={1.8} aria-hidden />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[15px] font-semibold text-text-primary">{m.label}</span>
                  {m.description && (
                    <span className="block truncate text-[12px] text-text-tertiary">{m.description}</span>
                  )}
                </span>
                {active && (
                  <span className="shrink-0 rounded-pill bg-accent px-2 py-0.5 text-[10px] font-semibold text-accent-on">
                    открыт
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
