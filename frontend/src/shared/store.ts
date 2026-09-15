import { useQuery } from "@tanstack/react-query";
import { create } from "zustand";
import { billingApi } from "./billing";
import { getPlan, type Plan, type PlanId } from "./plans";

/* Глобальный UI-state (zustand): тема, готовность инициализации,
   и текущий тариф пользователя. Серверные данные тут не живут —
   их держит TanStack Query. */

export type Theme = "light" | "dark";

const THEME_KEY = "ui:theme";
const PLAN_KEY = "billing:plan";

function readInitialTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  try {
    const saved = window.localStorage.getItem(THEME_KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    /* localStorage может быть недоступен */
  }
  const prefersLight = window.matchMedia?.("(prefers-color-scheme: light)").matches;
  return prefersLight ? "light" : "dark";
}

function readInitialPlan(): PlanId {
  if (typeof window === "undefined") return "free";
  try {
    const saved = window.localStorage.getItem(PLAN_KEY);
    if (saved === "free" || saved === "pro") return saved;
  } catch {
    /* ignore */
  }
  return "free";
}

function applyTheme(theme: Theme): void {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.theme = theme;
  try {
    window.localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* ignore */
  }
  try {
    const bg = getComputedStyle(document.documentElement)
      .getPropertyValue("--bg-base")
      .trim();
    const wa = window.Telegram?.WebApp;
    if (bg && wa) {
      wa.setBackgroundColor?.(bg);
      wa.setHeaderColor?.(bg);
    }
  } catch {
    /* ignore */
  }
}

function persistPlan(planId: PlanId): void {
  try {
    window.localStorage.setItem(PLAN_KEY, planId);
  } catch {
    /* ignore */
  }
}

interface UiState {
  ready: boolean;
  theme: Theme;
  planId: PlanId;
  setReady: (ready: boolean) => void;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
  setPlan: (planId: PlanId) => void;
}

const initialTheme = readInitialTheme();
applyTheme(initialTheme);
const initialPlan = readInitialPlan();

export const useUiStore = create<UiState>((set, get) => ({
  ready: false,
  theme: initialTheme,
  planId: initialPlan,
  setReady: (ready) => set({ ready }),
  setTheme: (theme) => {
    applyTheme(theme);
    set({ theme });
  },
  toggleTheme: () => {
    const next: Theme = get().theme === "dark" ? "light" : "dark";
    applyTheme(next);
    set({ theme: next });
  },
  setPlan: (planId) => {
    persistPlan(planId);
    set({ planId });
  },
}));

/* Читает текущий план: сервер — источник правды, UI-store — оптимистический кэш.
   Пока запрос идёт — показываем закэшированный локально план. Как только
   бэкенд отвечает, синхронизируем store, чтобы бейджи и лимиты обновились. */
export function useCurrentPlan(): Plan {
  const local = useUiStore((s) => s.planId);
  const setPlan = useUiStore((s) => s.setPlan);
  useQuery({
    queryKey: ["billing", "plan"],
    queryFn: async () => {
      const snap = await billingApi.getPlan();
      // Игнорируем битые/пустые ответы — иначе можно засунуть undefined
      // в store и потерять локальный план.
      if (
        (snap?.plan_id === "free" || snap?.plan_id === "pro") &&
        snap.plan_id !== local
      ) {
        setPlan(snap.plan_id);
      }
      return snap;
    },
    staleTime: 60_000,
    retry: 1,
  });
  return getPlan(local);
}
