import { Check, Flag, X } from "lucide-react";
import { timeAgo } from "../../../shared/format";
import type { CommentLog, CommentStatus } from "../types";

const STATUS_ICON: Record<CommentStatus, { Icon: typeof Check; cls: string }> = {
  posted: { Icon: Check, cls: "text-status-active" },
  failed: { Icon: X, cls: "text-status-critical" },
  flagged: { Icon: Flag, cls: "text-status-warning" },
};

/* Лог комментов, сгруппированный по постам (§ треб.): заголовок-разделитель
   на пост + карточки комментов. Длинный текст переносится и обрезается. */
export function CommentLogList({ logs }: { logs: CommentLog[] }) {
  if (logs.length === 0) {
    return <p className="text-[13px] text-text-tertiary">Комментариев пока нет.</p>;
  }

  // Группировка с сохранением порядка появления постов.
  const groups = new Map<number, CommentLog[]>();
  for (const log of logs) {
    const arr = groups.get(log.post_channel_msg_id) ?? [];
    arr.push(log);
    groups.set(log.post_channel_msg_id, arr);
  }

  return (
    <div className="flex flex-col gap-5">
      {[...groups.entries()].map(([postId, items]) => (
        <div key={postId}>
          <p className="mb-2 px-1 text-[12px] font-medium uppercase tracking-wide text-text-tertiary">
            Пост #{postId}
          </p>
          <div className="flex flex-col gap-2">
            {items.map((log) => {
              const { Icon, cls } = STATUS_ICON[log.status];
              return (
                <div key={log.id} className="card p-3.5">
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <span className="text-[12px] text-text-tertiary nums">
                      Аккаунт #{log.account_id}
                    </span>
                    <span className="flex items-center gap-1.5 text-[12px] text-text-tertiary">
                      {timeAgo(log.created_at)}
                      <Icon className={`h-3.5 w-3.5 ${cls}`} strokeWidth={2} aria-hidden />
                    </span>
                  </div>
                  <p className="line-clamp-3 whitespace-pre-wrap break-words text-[14px] leading-snug text-text-primary">
                    {log.comment_text}
                  </p>
                  {log.error && (
                    <p className="mt-1 line-clamp-2 break-words text-[12px] text-status-critical">
                      {log.error}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
