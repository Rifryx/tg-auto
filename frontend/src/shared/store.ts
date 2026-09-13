import { create } from "zustand";

/* Глобальный UI-state (zustand). Пока минимальный: цветовая схема из Telegram
   и флаг готовности инициализации. Серверные данные тут не живут — их держит
   TanStack Query. */
interface UiState {
  ready: boolean;
  colorScheme: "light" | "dark";
  setReady: (ready: boolean) => void;
  setColorScheme: (scheme: "light" | "dark") => void;
}

export const useUiStore = create<UiState>((set) => ({
  ready: false,
  colorScheme: "dark",
  setReady: (ready) => set({ ready }),
  setColorScheme: (colorScheme) => set({ colorScheme }),
}));
