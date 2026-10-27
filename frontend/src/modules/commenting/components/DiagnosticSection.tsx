import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { commentingApi } from "../api";

/** Диагностика «почему нейрокомментинг молчит».
 *
 *  Пользователь жаловался: «идёт куча логов, но ничего не комментируется,
 *  в статистике 0». Этот блок собирает в одной выдаче ответы на главные
 *  вопросы: включена ли кампания, есть ли discussion_group_id, какие
 *  аккаунты прикреплены и в каких статусах. Если всё зелёное, но
 *  комментов нет — значит listener поднят, но пост не ловится или
 *  runner падает (их события пишутся в live-таймлайн). */
export function DiagnosticSection({ campaignId }: { campaignId: number }) {
  const q = useQuery({
    queryKey: ["campaign", campaignId, "diagnostic"],
    queryFn: () => commentingApi.diagnostic(campaignId),
    refetchInterval: 15_000,
  });
  const d = q.data;
  if (!d) {
    return <p className="text-[13px] text-text-tertiary">Собираем диагностику…</p>;
  }
  const ok = d.warnings.length === 0;
  return (
    <div className="flex flex-col gap-3">
      {ok ? (
        <div className="flex items-start gap-2 rounded-chip border border-status-active/40 bg-status-active/10 px-3 py-2 text-[12px] text-status-active">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={2} aria-hidden />
          <span>
            Конфигурация в порядке: кампания включена, канал и обсуждения
            заданы, {d.assigned_count} аккаунт
            {d.assigned_count === 1 ? "" : "ов"} готов{d.assigned_count === 1 ? "" : "ы"} к работе.
            Если комментов всё равно нет — ищите событие в «События (live)».
          </span>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {d.warnings.map((w, i) => (
            <div
              key={i}
              className="flex items-start gap-2 rounded-chip border border-status-warning/40 bg-status-warning/10 px-3 py-2 text-[12px] text-status-warning"
            >
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={2} aria-hidden />
              <span>{w}</span>
            </div>
          ))}
        </div>
      )}

      <div className="rounded-chip border border-hairline bg-surface-1 p-3 text-[12px] text-text-secondary">
        <p className="mb-1 text-text-tertiary">Конфиг</p>
        <ul className="flex flex-col gap-0.5">
          <li>
            <strong>Источник каналов:</strong>{" "}
            {d.campaign.channel_source_mode === "by_account_subscriptions"
              ? "по подпискам аккаунта"
              : "ссылки на каналы"}
          </li>
          <li>
            <strong>Режим отбора постов:</strong> {d.campaign.post_selection_mode}
          </li>
          <li>
            <strong>Включено:</strong> {d.campaign.enabled ? "да" : "нет"}
          </li>
          <li>
            <strong>Прикреплено аккаунтов:</strong> {d.accounts.length} (в работе
            assigned: {d.assigned_count})
          </li>
          <li>
            <strong>Каналов для мониторинга:</strong> {d.channels.length}{" "}
            (готовы к работе: {d.channels_ready_count})
          </li>
          {d.last_timeline_event_ts != null && (
            <li>
              <strong>Последнее событие таймлайна:</strong>{" "}
              {new Date(d.last_timeline_event_ts * 1000).toLocaleString("ru-RU")}
            </li>
          )}
          {d.last_timeline_event_ts == null && (
            <li className="text-status-warning">
              <strong>Таймлайн пуст.</strong> Listener ни разу не записывал
              событий — либо воркер не поднят, либо не прошёл первый attach.
            </li>
          )}
        </ul>
      </div>

      {d.channels.length > 0 && (
        <div className="rounded-chip border border-hairline bg-surface-1 p-3 text-[12px] text-text-secondary">
          <p className="mb-2 text-text-tertiary">Каналы кампании</p>
          <ul className="flex flex-col gap-1">
            {d.channels.map((ch) => (
              <li
                key={ch.id}
                className={`flex items-start gap-2 ${
                  ch.status === "working" && ch.has_discussion
                    ? ""
                    : "text-status-warning"
                }`}
              >
                <span className="shrink-0">
                  {ch.status === "working" && ch.has_discussion ? "✓" : "⚠"}
                </span>
                <span className="min-w-0 flex-1">
                  <strong>{ch.ref}</strong>{" "}
                  <span className="opacity-80">(акк. #{ch.account_id})</span> —{" "}
                  статус: <strong>{ch.status}</strong>
                  {!ch.has_discussion && ", нет обсуждений"}
                  {ch.error && (
                    <>
                      <br />
                      <span className="opacity-80">Ошибка: {ch.error}</span>
                    </>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
