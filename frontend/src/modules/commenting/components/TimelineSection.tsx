import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Loader2,
  Radio,
  RadioTower,
  Send,
  XCircle,
} from "lucide-react";
import { commentingApi } from "../api";
import type { TimelineKind } from "../types";

/** Live-таймлайн кампании: что listener/runner видел последние ~N событий.
 *  Пользователь жаловался: «в блоке запущенной кампании нет логов что где и
 *  когда» — теперь каждый шаг (пост получен → отфильтрован / поставлен →
 *  опубликован / упал) виден с иконкой и временем. Поллим раз в 5 с, пока
 *  экран открыт. Источник — Redis TTL 24h (modules/commenting/worker/timeline.py). */
export function TimelineSection({ campaignId }: { campaignId: number }) {
  const q = useQuery({
    queryKey: ["campaign", campaignId, "timeline"],
    queryFn: () => commentingApi.timeline(campaignId, 100),
    refetchInterval: 5_000,
    staleTime: 2_000,
  });
  const events = q.data?.events ?? [];
  if (events.length === 0) {
    return (
      <p className="text-[13px] text-text-tertiary">
        Пока пусто. Сюда попадут события слушателя и runner'а, как только
        кампания получит первый пост.
      </p>
    );
  }
  return (
    // Своя прокрутка: событий копится много (listener переподключается часто),
    // и раньше они растягивали весь экран. Крутим внутри блока. Бэкенд держит
    // хвост в Redis (capped-list, см. timeline.py), так что лента не растёт без
    // границы.
    <div className="max-h-96 overflow-y-auto overscroll-contain rounded-chip border border-hairline bg-surface-1/40 px-3">
      <ul className="flex flex-col">
        {events.map((e, i) => (
          <li
            key={`${e.ts}-${i}`}
            className={`flex items-start gap-3 py-2.5 ${i > 0 ? "border-t border-hairline" : ""}`}
          >
            <TimelineIcon kind={e.kind} />
            <div className="min-w-0 flex-1">
              <p className="text-[14px] text-text-primary">{e.message}</p>
              <p className="text-[12px] text-text-tertiary">{formatWhen(e.ts)}</p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function TimelineIcon({ kind }: { kind: TimelineKind | string }) {
  const map: Record<string, { Icon: typeof Clock; cls: string }> = {
    listener_online: { Icon: RadioTower, cls: "text-status-active" },
    listener_offline: { Icon: Radio, cls: "text-text-tertiary" },
    post_received: { Icon: Radio, cls: "text-text-secondary" },
    post_filtered: { Icon: AlertCircle, cls: "text-text-tertiary" },
    post_queued: { Icon: Clock, cls: "text-status-warning" },
    generation_started: { Icon: Loader2, cls: "text-text-secondary" },
    comment_scheduled: { Icon: Clock, cls: "text-status-warning" },
    comment_posted: { Icon: Send, cls: "text-status-active" },
    comment_failed: { Icon: XCircle, cls: "text-status-critical" },
    comment_skipped: { Icon: AlertCircle, cls: "text-text-tertiary" },
    reaction_set: { Icon: CheckCircle2, cls: "text-status-active" },
    no_account: { Icon: AlertCircle, cls: "text-status-warning" },
  };
  const { Icon, cls } = map[kind] ?? { Icon: Clock, cls: "text-text-tertiary" };
  return <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${cls}`} strokeWidth={1.8} aria-hidden />;
}

function formatWhen(ts: number): string {
  const date = new Date(ts * 1000);
  const now = new Date();
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();
  const time = date.toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  if (sameDay) return time;
  const dateStr = date.toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
  });
  return `${dateStr} ${time}`;
}
