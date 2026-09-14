import { ExternalLink } from "lucide-react";
import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { isBrowserDev, isTelegram } from "../../shared/tg";
import { BottomNav } from "./BottomNav";

/* Каркас экрана: прокручиваемый контент + плавающая капсула навбара снизу.
   На flow-экранах (онбординг аккаунта, новая кампания — фокус «одно действие»
   с липкой кнопкой снизу) навбар скрыт, чтобы кнопка не пряталась под ним. */
export function AppLayout({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const chromeless = pathname.endsWith("/new");
  return (
    <div className="mx-auto flex min-h-full max-w-[440px] flex-col bg-bg-base">
      {isBrowserDev && !isTelegram && <DevBar />}
      <main className={`flex flex-1 flex-col px-5 pt-3 ${chromeless ? "pb-6" : "pb-32"}`}>
        {children}
      </main>
      {!chromeless && <BottomNav />}
    </div>
  );
}

/* Dev-подсказка: открыть ту же страницу в обычном браузере без Telegram-обёртки. */
function DevBar() {
  return (
    <div className="flex items-center justify-between px-5 py-2 text-[11px] text-text-tertiary">
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
