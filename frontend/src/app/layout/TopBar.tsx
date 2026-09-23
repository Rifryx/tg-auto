import { Menu, Moon, Sun } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { PlanBadge } from "../../shared/PlanBadge";
import { hapticSelection } from "../../shared/tg";
import { useUiStore } from "../../shared/store";
import { SideDrawer } from "./SideDrawer";

/* Верхняя панель главного экрана:
   - слева иконка меню (три полосы) — открывает боковой дровер;
   - по центру пилюля с текущим тарифом (Free/Pro) — кликабельно, ведёт на биллинг;
   - справа переключатель темы (луна/солнце). */
export function TopBar() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const theme = useUiStore((s) => s.theme);
  const toggleTheme = useUiStore((s) => s.toggleTheme);

  return (
    <>
      {/* На десктопе меню, тариф и тема живут в боковой панели. */}
      <div className="mb-3 flex items-center justify-between gap-2 lg:hidden">
        <button
          type="button"
          onClick={() => {
            hapticSelection();
            setOpen(true);
          }}
          aria-label="Открыть меню"
          className="inline-flex h-10 w-10 items-center justify-center rounded-pill border border-hairline bg-surface-1 text-text-primary active:bg-surface-2"
        >
          <Menu className="h-5 w-5" strokeWidth={1.8} aria-hidden />
        </button>

        <button
          type="button"
          onClick={() => {
            hapticSelection();
            navigate("/billing");
          }}
          aria-label="Ваш тариф"
          className="rounded-pill transition-transform active:scale-[0.98]"
        >
          <PlanBadge size="md" />
        </button>

        <button
          type="button"
          onClick={() => {
            hapticSelection();
            toggleTheme();
          }}
          aria-label={theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему"}
          className="inline-flex h-10 w-10 items-center justify-center rounded-pill border border-hairline bg-surface-1 text-text-primary active:bg-surface-2"
        >
          {theme === "dark" ? (
            <Sun className="h-5 w-5" strokeWidth={1.8} aria-hidden />
          ) : (
            <Moon className="h-5 w-5" strokeWidth={1.8} aria-hidden />
          )}
        </button>
      </div>

      <SideDrawer open={open} onClose={() => setOpen(false)} />
    </>
  );
}
