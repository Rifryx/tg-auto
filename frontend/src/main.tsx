import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { initTelegram } from "./shared/tg";
import { useUiStore } from "./shared/store";
import { showToast } from "./shared/toast";
import "./styles/index.css";

initTelegram();
useUiStore.getState().setReady(true);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 10_000, retry: 1, refetchOnWindowFocus: false },
  },
  // Единая точка обработки ошибок мутаций: любая упавшая мутация без своего
  // onError покажет тост. Мутации, что рулят ошибкой сами (напр. показывают
  // inline-сообщение), могут передать meta.silent = true.
  mutationCache: new MutationCache({
    onError: (error, _vars, _ctx, mutation) => {
      if (mutation.meta?.silent) return;
      const msg =
        (error as { message?: string })?.message || "Не удалось выполнить действие";
      showToast(msg, "error");
    },
  }),
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
