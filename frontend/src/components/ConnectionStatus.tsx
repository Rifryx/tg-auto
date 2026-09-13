import { useQuery } from "@tanstack/react-query";
import { api } from "../shared/api";

/* Индикатор связи с backend. Заодно — тот самый запрос к API, который в dev
   уходит с фейковым initData (заголовки добавляет shared/api.ts). Статусная
   точка по §7 брифа: зелёная — на связи, красная — нет. */
export function ConnectionStatus() {
  const { isSuccess, isError, isLoading } = useQuery({
    queryKey: ["health"],
    queryFn: () => api.get<{ status: string }>("/health"),
    retry: 0,
  });

  const { dot, label } = isLoading
    ? { dot: "bg-status-neutral", label: "Проверяем связь…" }
    : isSuccess
      ? { dot: "bg-status-active", label: "Сервер на связи" }
      : isError
        ? { dot: "bg-status-critical", label: "Нет связи с сервером" }
        : { dot: "bg-status-neutral", label: "—" };

  return (
    <div className="flex items-center gap-2 text-[13px] text-text-secondary">
      <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden />
      {label}
    </div>
  );
}
