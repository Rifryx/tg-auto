import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Plus, RefreshCw } from "lucide-react";
import { useState } from "react";
import { channelsApi } from "../../../shared/accounts";
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
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["campaign", campaignId, "diagnostic"],
    queryFn: () => commentingApi.diagnostic(campaignId),
    refetchInterval: 15_000,
  });
  const resync = useMutation({
    mutationFn: () => commentingApi.resyncChannels(campaignId),
    onSuccess: () => {
      // После enqueue backend-воркер в фоне обновит MonitoredChannel.
      // Через 3-5 с кидаем refetch диагностики — пусть юзер увидит новые
      // статусы без ручного «обновить».
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ["campaign", campaignId, "diagnostic"] });
        qc.invalidateQueries({ queryKey: ["campaign", campaignId, "timeline"] });
      }, 3_500);
    },
  });
  const d = q.data;
  if (!d) {
    return <p className="text-[13px] text-text-tertiary">Собираем диагностику…</p>;
  }
  const ok = d.warnings.length === 0;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-end">
        <button
          type="button"
          onClick={() => resync.mutate()}
          disabled={resync.isPending}
          className="inline-flex items-center gap-1.5 rounded-pill border border-hairline bg-surface-1 px-3 py-1.5 text-[12px] text-text-secondary hover:text-text-primary active:bg-surface-2 disabled:opacity-60"
        >
          <RefreshCw
            className={`h-3.5 w-3.5 ${resync.isPending ? "animate-spin" : ""}`}
            strokeWidth={2}
            aria-hidden
          />
          {resync.isPending ? "Переподключаем…" : "Переподключить каналы"}
        </button>
      </div>
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

      {d.accounts.length > 0 &&
        d.campaign.channel_source_mode === "by_account_subscriptions" && (
          <AddChannelForm
            accountId={d.accounts[0].id}
            onDone={() => {
              qc.invalidateQueries({
                queryKey: ["campaign", campaignId, "diagnostic"],
              });
            }}
          />
        )}

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

/** Форма «Добавить канал по ссылке» на уровне аккаунта.
 *
 *  Нужна когда авто-sync подписок не подхватил нужный канал (например, он не
 *  broadcast, нет linked chat в метаданных на момент синка, или аккаунт
 *  подписан в архиве/папке). Пользователь руками вводит t.me/username —
 *  бэкенд резолвит, подписывает если нужно, читает discussion_group. */
function AddChannelForm({
  accountId,
  onDone,
}: {
  accountId: number;
  onDone: () => void;
}) {
  const [ref, setRef] = useState("");
  const add = useMutation({
    mutationFn: (refs: string[]) => channelsApi.add(accountId, refs, false),
    onSuccess: () => {
      setRef("");
      // Backend ставит resolve в очередь; реальный статус подъедет через ~5-10 с.
      setTimeout(onDone, 5_000);
    },
  });
  const refs = ref
    .split(/[\s,;]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  const canAdd = refs.length > 0 && !add.isPending;
  return (
    <div className="rounded-chip border border-hairline bg-surface-1 p-3">
      <p className="mb-2 text-[12px] text-text-tertiary">
        Канал не попал в автосинк? Добавьте его вручную — @username или
        https://t.me/… (можно сразу несколько через пробел/запятую).
      </p>
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          type="text"
          value={ref}
          onChange={(e) => setRef(e.target.value)}
          placeholder="@mychannel или https://t.me/mychannel"
          className="w-full rounded-xl border border-hairline bg-surface-2 p-2 text-[14px] text-text-primary placeholder:text-text-tertiary focus:border-strong focus:outline-none"
        />
        <button
          type="button"
          onClick={() => canAdd && add.mutate(refs)}
          disabled={!canAdd}
          className="inline-flex h-10 shrink-0 items-center justify-center gap-1.5 rounded-pill bg-accent px-4 text-[13px] font-semibold text-accent-on active:opacity-80 disabled:bg-surface-2 disabled:text-text-tertiary"
        >
          <Plus className="h-4 w-4" strokeWidth={2.4} aria-hidden />
          {add.isPending ? "Добавляем…" : "Добавить"}
        </button>
      </div>
      {add.isError && (
        <p className="mt-2 text-[12px] text-status-critical">
          Не удалось добавить. Проверьте ссылку.
        </p>
      )}
      {add.isSuccess && (
        <p className="mt-2 text-[12px] text-status-active">
          Канал поставлен в очередь на разрешение. Через ~10 с увидите его в
          списке каналов кампании.
        </p>
      )}
    </div>
  );
}
