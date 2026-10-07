/* Обёртка над window.Telegram.WebApp (PROJECT-STAGES §7/§11).
 *
 * Единственная точка доступа к Telegram SDK: initData, тема, haptic, MainButton.
 * Вне Telegram (dev/браузер, или ?dev=1) — фолбэк на фейковый initData из
 * VITE_DEV_USER_ID, чтобы фронт работал без реального Mini App окружения. */

type HapticStyle = "light" | "medium" | "heavy" | "rigid" | "soft";

interface TelegramWebApp {
  initData: string;
  colorScheme: "light" | "dark";
  themeParams: Record<string, string>;
  ready(): void;
  expand(): void;
  setHeaderColor?(color: string): void;
  setBackgroundColor?(color: string): void;
  HapticFeedback?: {
    impactOccurred(style: HapticStyle): void;
    notificationOccurred(type: "error" | "success" | "warning"): void;
    selectionChanged(): void;
  };
  MainButton?: {
    setText(text: string): void;
    show(): void;
    hide(): void;
    enable(): void;
    disable(): void;
    onClick(cb: () => void): void;
    offClick(cb: () => void): void;
  };
  /** Открыть инвойс (Stars/иной) по ссылке; статус — в колбэке. */
  openInvoice?(
    url: string,
    callback?: (status: "paid" | "cancelled" | "failed" | "pending") => void,
  ): void;
  /** Открыть внешнюю ссылку (Crypto Bot pay_url) вне Mini App. */
  openLink?(url: string, options?: { try_instant_view?: boolean }): void;
  openTelegramLink?(url: string): void;
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

const params = new URLSearchParams(window.location.search);

/** Форсированный «браузерный» режим без tg-обёртки (?dev=1) или сборка dev. */
export const isBrowserDev =
  import.meta.env.DEV || params.get("dev") === "1";

function webApp(): TelegramWebApp | undefined {
  return window.Telegram?.WebApp;
}

/** Реальное Telegram-окружение (есть SDK и непустой initData). */
export const isTelegram = Boolean(webApp()?.initData) && params.get("dev") !== "1";

function buildDevInitData(): string {
  const userId = import.meta.env.VITE_DEV_USER_ID ?? "1";
  const user = encodeURIComponent(
    JSON.stringify({ id: Number(userId), first_name: "Dev", username: "dev" }),
  );
  const authDate = Math.floor(Date.now() / 1000);
  // Подпись фейковая: бэкенд в DEV_MODE её не проверяет (auth.py).
  return `user=${user}&auth_date=${authDate}&hash=dev`;
}

/** initData для авторизации на бэкенде (реальный из Telegram или фейковый в dev). */
export function getInitData(): string {
  const real = webApp()?.initData;
  if (real && params.get("dev") !== "1") return real;
  if (isBrowserDev) return buildDevInitData();
  return "";
}

/** Идентификатор dev-пользователя для заголовка X-Dev-User (только dev). */
export function getDevUserId(): string | null {
  return isBrowserDev ? String(import.meta.env.VITE_DEV_USER_ID ?? "1") : null;
}

/** Инициализация: сообщаем Telegram о готовности и разворачиваем на всю высоту. */
export function initTelegram(): void {
  const wa = webApp();
  if (!wa) return;
  try {
    wa.ready();
    wa.expand();
    // Цвет берём из токена --bg-base (tokens.css) — без хардкода hex в коде.
    const bg = getComputedStyle(document.documentElement)
      .getPropertyValue("--bg-base")
      .trim();
    if (bg) {
      wa.setBackgroundColor?.(bg);
      wa.setHeaderColor?.(bg);
    }
  } catch {
    /* окружение без части API — не критично */
  }
}

/** Открыть инвойс Stars. Вне Telegram — fallback на window.open. */
export function openInvoice(
  url: string,
  callback?: (status: "paid" | "cancelled" | "failed" | "pending") => void,
): void {
  const wa = webApp();
  if (wa?.openInvoice) {
    wa.openInvoice(url, callback);
    return;
  }
  // Dev/браузер: открываем ссылку и считаем статус неизвестным (pending) —
  // поток оплаты в DEV подтверждается через check-эндпоинт.
  try {
    window.open(url, "_blank", "noopener");
  } catch {
    /* ignore */
  }
  callback?.("pending");
}

/** Открыть внешнюю ссылку (Crypto Bot). Вне Telegram — window.open. */
export function openExternal(url: string): void {
  const wa = webApp();
  if (url.includes("t.me/") && wa?.openTelegramLink) {
    wa.openTelegramLink(url);
    return;
  }
  if (wa?.openLink) {
    wa.openLink(url);
    return;
  }
  try {
    window.open(url, "_blank", "noopener");
  } catch {
    /* ignore */
  }
}

/** Тактильный отклик (no-op вне Telegram). */
export function haptic(style: HapticStyle = "light"): void {
  webApp()?.HapticFeedback?.impactOccurred(style);
}

export function hapticSelection(): void {
  webApp()?.HapticFeedback?.selectionChanged();
}

/** Управление нативной MainButton (no-op вне Telegram). */
export const mainButton = {
  set(text: string, onClick: () => void): void {
    const btn = webApp()?.MainButton;
    if (!btn) return;
    btn.setText(text);
    btn.onClick(onClick);
    btn.show();
  },
  hide(): void {
    webApp()?.MainButton?.hide();
  },
};
