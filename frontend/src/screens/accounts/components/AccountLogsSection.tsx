import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Flag } from "lucide-react";
import { accountsApi } from "../../../shared/accounts";
import { timeAgo } from "../../../shared/format";
import type { CommentLog, CommentStatus } from "../../../shared/types";
import { Section } from "./ui";

/* Журнал аккаунта («Логи», этап 3): история комментариев + ошибки Telegram API.
 *
 * Показывает, скольким постам оставлен комментарий, и подсвечивает ответы
 * Telegram API (FLOOD_WAIT_X, PEER_FLOOD и т.п.) из поля error. */
const STATUS_META: Record<CommentStatus, { label: string; cls: string; Icon: typeof CheckCircle2 }> = {
  posted: { label: "опубликован", cls: "text-status-active", Icon: CheckCircle2 },
  failed: { label: "ошибка", cls: "text-status-critical", Icon: AlertTriangle },
  flagged: { label: "на модерации", cls: "text-status-warning", Icon: Flag },
};

export function AccountLogsSection({ accountId }: { accountId: number }) {
  const logs = useQuery({
    queryKey: ["account", accountId, "comment-logs"],
    queryFn: () => accountsApi.commentLogs(accountId),
    refetchInterval: 20_000,
  });

  const rows = logs.data ?? [];
  const posted = rows.filter((r) => r.status === "posted").length;
  const failed = rows.filter((r) => r.status === "failed").length;

  return (
    <Section title="Журнал">
      {logs.isLoading ? (
        <p className="text-[13px] text-text-tertiary">Загрузка…</p>
      ) : rows.length === 0 ? (
        <p className="text-[13px] text-text-tertiary">
          Активности в кампаниях пока нет.
        </p>
      ) : (
        <>
          <div className="mb-3 flex gap-4 text-[12px]">
            <span className="text-status-active">Опубликовано: {posted}</span>
            {failed > 0 && <span className="text-status-critical">Ошибок: {failed}</span>}
          </div>
          <ul className="flex flex-col">
            {rows.map((log, i) => (
              <LogRow key={log.id} log={log} border={i > 0} />
            ))}
          </ul>
        </>
      )}
    </Section>
  );
}

function LogRow({ log, border }: { log: CommentLog; border: boolean }) {
  const meta = STATUS_META[log.status];
  const { Icon } = meta;
  return (
    <li className={`flex items-start gap-3 py-2.5 ${border ? "border-t border-hairline" : ""}`}>
      <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${meta.cls}`} strokeWidth={1.8} aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] text-text-primary">{log.comment_text}</p>
        <p className="text-[12px] text-text-tertiary">
          <span className={meta.cls}>{meta.label}</span> · {timeAgo(log.created_at)}
        </p>
        {log.error && (
          <p className="mt-0.5 break-all font-mono text-[11px] text-status-critical">
            {log.error}
          </p>
        )}
      </div>
    </li>
  );
}
