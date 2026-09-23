import { ExternalLink } from "lucide-react";
import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { isBrowserDev, isTelegram } from "../../shared/tg";
import { BottomNav } from "./BottomNav";
import { DesktopSidebar } from "./DesktopSidebar";

/* Каркас экрана.
   Телефон (<lg): колонка 440px + плавающая капсула навбара снизу. На
   flow-экранах (…/new: одно действие + липкая кнопка) навбар скрыт.
   Десктоп (lg+): боковая панель со всеми разделами + широкая область
   контента; нижний навбар не показывается вовсе. */
export function AppLayout({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const chromeless = pathname.endsWith("/new");
  return (
    <div className="flex min-h-full bg-bg-base">
      <DesktopSidebar />
      <div className="mx-auto flex min-h-full w-full min-w-0 max-w-[440px] flex-col lg:max-w-[1200px] lg:px-10">
        {isBrowserDev && !isTelegram && <DevBar />}
        <main
          className={`flex flex-1 flex-col px-5 pt-3 lg:px-0 lg:pb-12 lg:pt-8 ${
            chromeless ? "pb-6" : "pb-32"
          }`}
        >
          {children}
        </main>
      </div>
      {!chromeless && (
        <div className="lg:hidden">
          <BottomNav />
        </div>
      )}
    </div>
  );
}

/* Dev-подсказка: открыть ту же страницу в обычном браузере без Telegram-обёртки. */
function DevBar() {
  return (
    <div className="flex items-center justify-between px-5 py-2 text-[11px] text-text-tertiary lg:px-0">
      <span>dev-режим</span>
      <a
        href="/?dev=1"
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1 rounded-pill border border-hairline bg-surface-1 px-2.5 py-1 text-text-secondary active:text-text-primary"
      >
        <ExternalLink className="h-3 w-3" strokeWidth={1.8} aria-hidden />
        Открыть в браузере
      </a>
    </div>
  );
}

/* Заголовок экрана H1 (§3) + опциональное действие справа. */
export function ScreenHeader({
  title,
  action,
}: {
  title: string;
  action?: ReactNode;
}) {
  return (
    <header className="mb-6 flex items-center justify-between">
      <h1 className="screen-title">{title}</h1>
      {action}
    </header>
  );
}
