import { Bell, Menu, Moon, Sun } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { hapticSelection } from "../../shared/tg";
import { useUiStore } from "../../shared/store";
import { SideDrawer } from "./SideDrawer";

export function TopBar() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const theme = useUiStore((s) => s.theme);
  const toggleTheme = useUiStore((s) => s.toggleTheme);

  return (
    <>
      <div className="mb-2 flex items-center justify-between gap-2 lg:hidden">
        <button
          type="button"
          onClick={() => {
            hapticSelection();
            setOpen(true);
          }}
          aria-label="Открыть меню"
          className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-surface-2 text-text-primary active:opacity-70"
        >
          <Menu className="h-5 w-5" strokeWidth={1.8} aria-hidden />
        </button>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => {
              hapticSelection();
              navigate("/more/audit");
            }}
            aria-label="Уведомления"
            className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-surface-2 text-text-secondary active:opacity-70"
          >
            <Bell className="h-[18px] w-[18px]" strokeWidth={1.8} aria-hidden />
          </button>

          <button
            type="button"
            onClick={() => {
              hapticSelection();
              toggleTheme();
            }}
            aria-label={theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему"}
            className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-surface-2 text-text-secondary active:opacity-70"
          >
            {theme === "dark" ? (
              <Sun className="h-[18px] w-[18px]" strokeWidth={1.8} aria-hidden />
            ) : (
              <Moon className="h-[18px] w-[18px]" strokeWidth={1.8} aria-hidden />
            )}
          </button>
        </div>
      </div>

      <SideDrawer open={open} onClose={() => setOpen(false)} />
    </>
  );
}
