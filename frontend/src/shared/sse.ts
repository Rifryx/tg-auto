import { useEffect, useRef } from "react";
import { subscribeStream } from "./api";

/* Живые обновления через SSE (поверх fetch с auth-заголовками, см. api.ts).
   onMessage держим в ref, чтобы не пересоздавать подписку при каждом рендере. */
export function useSse(
  path: string | null,
  onMessage: (data: unknown) => void,
  enabled = true,
): void {
  const cb = useRef(onMessage);
  cb.current = onMessage;

  useEffect(() => {
    if (!path || !enabled) return;
    const unsub = subscribeStream(path, (d) => cb.current(d));
    return unsub;
  }, [path, enabled]);
}

/* Канал живых событий дашборда: account_status + health_alert (промпт 23
   публикует их в Redis). Бэкенд должен отдавать их одним SSE-эндпоинтом —
   когда он появится, дашборд начнёт обновляться мгновенно; до тех пор
   подписка тихо не подключится, а данные освежает 30-сек refetch. */
export const MONITORING_STREAM = "/monitoring/stream";

export interface LiveEvent {
  type?: "account_status" | "health_alert" | "login";
  account_id?: number;
  [key: string]: unknown;
}
