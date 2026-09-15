import { CreditCard, Settings, Shield, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useIsAdmin } from "../../shared/admin";
import { hapticSelection } from "../../shared/tg";

interface SideDrawerProps {
  open: boolean;
  onClose: () => void;
}

interface MenuItem {
  label: string;
  description?: string;
  icon: LucideIcon;
  to: string;
  accent?: boolean;
}

const ITEMS: MenuItem[] = [
  {
    label: "Тариф и лимиты",
    description: "Оплата, апгрейд плана, ваши лимиты",
    icon: CreditCard,
    to: "/billing",
    accent: true,
  },
  {
    label: "Настройки",
    description: "Профиль, персоны, прокси",
    icon: Settings,
    to: "/more",
  },
];

/* Боковой дровер, выезжающий слева направо (§ выдвижное меню).
   Пункт «Админ» появляется ТОЛЬКО у пользователей, которых сервер отметил
   админом (GET /admin/me → 200). Для остальных его нет в DOM. */
export function SideDrawer({ open, onClose }: SideDrawerProps) {
  const navigate = useNavigate();
  const { isAdmin } = useIsAdmin();

  // Esc закрывает дровер + блокируем скролл фона.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  return (
    <div
      className={`fixed inset-0 z-50 ${open ? "pointer-events-auto" : "pointer-events-none"}`}
      aria-hidden={!open}
    >
      {/* Оверлей */}
      <div
        onClick={onClose}
        className={`absolute inset-0 bg-black/50 transition-opacity duration-200 ${
          open ? "opacity-100" : "opacity-0"
        }`}
      />

      {/* Панель */}
      <aside
        role="dialog"
        aria-modal="true"
        className={`absolute left-0 top-0 flex h-full w-[82%] max-w-[360px] flex-col border-r border-hairline bg-bg-elevated transition-transform duration-200 ease-out ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
        style={{ paddingTop: "env(safe-area-inset-top)" }}
      >
        <div className="flex items-center justify-between px-5 pt-4">
          <span className="text-[13px] font-semibold uppercase tracking-wide text-text-tertiary">
            Меню
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть меню"
            className="inline-flex h-9 w-9 items-center justify-center rounded-pill border border-hairline bg-surface-1 text-text-primary active:bg-surface-2"
          >
            <X className="h-4 w-4" strokeWidth={1.8} aria-hidden />
          </button>
        </div>

        <div className="mt-5 flex flex-col gap-2 px-4">
          {isAdmin && (
            <button
              key="admin"
              type="button"
              onClick={() => {
                hapticSelection();
                onClose();
                navigate("/admin");
              }}
              className="flex items-center gap-3 rounded-card border border-strong bg-surface-2 px-4 py-3 text-left text-text-primary active:opacity-80"
            >
              <Shield className="h-5 w-5 shrink-0" strokeWidth={1.8} aria-hidden />
              <div className="flex min-w-0 flex-col">
                <span className="text-[15px] font-semibold leading-tight">Админ</span>
                <span className="text-[12px] text-text-tertiary">
                  Управление пользователями и планами
                </span>
              </div>
            </button>
          )}
          {ITEMS.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.to}
                type="button"
                onClick={() => {
                  hapticSelection();
                  onClose();
                  navigate(item.to);
                }}
                className={[
                  "flex items-center gap-3 rounded-card border border-hairline px-4 py-3 text-left transition-colors",
                  item.accent
                    ? "bg-accent text-accent-on"
                    : "bg-surface-1 text-text-primary active:bg-surface-2",
                ].join(" ")}
              >
                <Icon className="h-5 w-5 shrink-0" strokeWidth={1.8} aria-hidden />
                <div className="flex min-w-0 flex-col">
                  <span className="text-[15px] font-semibold leading-tight">
                    {item.label}
                  </span>
                  {item.description && (
                    <span
                      className={`text-[12px] leading-snug ${
                        item.accent ? "opacity-80" : "text-text-tertiary"
                      }`}
                    >
                      {item.description}
                    </span>
                  )}
                </div>
              </button>
            );
          })}
        </div>

        <div className="mt-auto px-5 pb-6 pt-4 text-[11px] text-text-tertiary">
          Скоро здесь появятся уведомления, история операций и приглашения.
        </div>
      </aside>
    </div>
  );
}
