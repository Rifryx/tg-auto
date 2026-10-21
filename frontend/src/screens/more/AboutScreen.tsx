import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../../shared/api";
import { BackHeader } from "./PersonasScreen";

export interface AppContent {
  about: { app_name: string; version: string; body: string };
  activity: { timezone: string; window_start: string; window_end: string };
  support: {
    manager_username: string;
    manager_url: string;
    in_app_enabled: boolean;
    intro: string;
  };
}

export function useAppContent() {
  return useQuery({
    queryKey: ["app", "content"],
    queryFn: () => api.get<AppContent>("/app/content"),
    staleTime: 5 * 60_000,
  });
}

export function AboutScreen() {
  const navigate = useNavigate();
  const { data } = useAppContent();
  const about = data?.about;
  return (
    <div className="pb-6 pt-1">
      <BackHeader title="О приложении" onBack={() => navigate("/more")} />
      <div className="card p-5">
        <p className="text-[17px] font-semibold text-text-primary">
          {about?.app_name ?? "Neuro-Commenting"}
        </p>
        <p className="mt-1 text-[13px] text-text-secondary">
          Версия {about?.version ?? "0.1.0"}
        </p>
        <p className="mt-4 whitespace-pre-line text-[14px] leading-relaxed text-text-secondary">
          {about?.body ??
            "Панель управления Telegram-аккаунтами: прогрев, пул и модуль комментирования. Работает как Telegram Mini App."}
        </p>
      </div>
    </div>
  );
}
