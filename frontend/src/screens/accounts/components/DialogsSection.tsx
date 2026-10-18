import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Hash, LogOut, Megaphone, RefreshCw, Users } from "lucide-react";
import { useState } from "react";
import { accountsApi } from "../../../shared/accounts";
import type { AccountDialog } from "../../../shared/types";
import { hapticSelection } from "../../../shared/tg";
import { Section } from "./ui";

/* #5: все каналы/группы аккаунта + выход/очистка. Снапшот живёт в Redis на
   сервере, обновляется по кнопке (воркер тянет get_dialogs). Работает вместе с
   подпиской по ссылкам: подписался → «Обновить» → появится здесь. */
export function DialogsSection({ accountId }: { accountId: number }) {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [confirmClear, setConfirmClear] = useState(false);

  type DialogsData = { synced: boolean; synced_at: string | null; items: AccountDialog[] };
  const key = ["account", accountId, "dialogs"];
  const dialogs = useQuery({ queryKey: key, queryFn: () => accountsApi.dialogs(accountId) });

  // Снапшот снимается воркером асинхронно (leave + повторный get_dialogs), время
  // выполнения плавает — поэтому обновляем список НЕСКОЛЬКО раз, последний
  // рефетч приходит на уже актуальный снапшот.
  const refetchSoon = () =>
    [1500, 4000, 8000].forEach((ms) =>
      window.setTimeout(() => qc.invalidateQueries({ queryKey: key }), ms),
    );

  const sync = useMutation({
    mutationFn: () => accountsApi.syncDialogs(accountId),
    onSuccess: () => {
      hapticSelection();
      refetchSoon();
    },
  });
  const leave = useMutation({
    mutationFn: (body: { dialog_ids?: number[]; all?: boolean }) =>
      accountsApi.leaveDialogs(accountId, body),
    // Оптимистично убираем покинутые из списка сразу, чтобы UI обновился без
    // ожидания воркера; затем refetchSoon сверит со снапшотом.
    onMutate: (body) => {
      const removing = new Set(selected);
      qc.setQueryData<DialogsData>(key, (old) =>
        old
          ? {
              ...old,
              items: body.all ? [] : old.items.filter((d) => !removing.has(d.id)),
            }
          : old,
      );
    },
    onSuccess: () => {
      setSelected(new Set());
      setConfirmClear(false);
      refetchSoon();
    },
  });

  const items: AccountDialog[] = dialogs.data?.items ?? [];
  const synced = dialogs.data?.synced ?? false;
  const busy = sync.isPending || leave.isPending;

  const toggle = (id: number) =>
    setSelected((s) => {
      const next = new Set(s);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  return (
    <Section
      title="Чаты и каналы"
      action={
        <button
          type="button"
          onClick={() => sync.mutate()}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-pill border border-hairline bg-surface-1 px-3 py-1.5 text-[12px] font-semibold text-text-secondary active:bg-surface-2 disabled:opacity-50"
        >
          <RefreshCw
            className={`h-3.5 w-3.5 ${sync.isPending ? "animate-spin" : ""}`}
            strokeWidth={2}
            aria-hidden
          />
          Обновить
        </button>
      }
    >
      <div className="card p-4">
        {!synced && !dialogs.isLoading && (
          <p className="py-2 text-center text-[13px] text-text-tertiary">
            Нажмите «Обновить», чтобы загрузить список чатов и каналов аккаунта.
          </p>
        )}
        {synced && items.length === 0 && (
          <p className="py-2 text-center text-[13px] text-text-tertiary">
            Аккаунт не состоит ни в одном канале/группе.
          </p>
        )}

        {items.length > 0 && (
          <div className="flex max-h-[360px] flex-col gap-1 overflow-y-auto overscroll-contain pr-1">
            {items.map((d) => {
              const checked = selected.has(d.id);
              return (
                <button
                  key={d.id}
                  type="button"
                  onClick={() => toggle(d.id)}
                  className={`flex items-center gap-3 rounded-chip px-2 py-2 text-left transition-colors ${
                    checked ? "bg-surface-2" : "active:bg-surface-1"
                  }`}
                >
                  <span
                    aria-hidden
                    className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md border ${
                      checked ? "border-accent bg-accent text-accent-on" : "border-hairline"
                    }`}
                  >
                    {checked && <span className="text-[12px] leading-none">✓</span>}
                  </span>
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface-2 text-text-tertiary">
                    {d.kind === "channel" ? (
                      <Megaphone className="h-4 w-4" strokeWidth={1.8} aria-hidden />
                    ) : (
                      <Hash className="h-4 w-4" strokeWidth={1.8} aria-hidden />
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[14px] text-text-primary">
                      {d.title || (d.username ? `@${d.username}` : "Без названия")}
                    </span>
                    <span className="block truncate text-[11px] text-text-tertiary">
                      {d.username ? `@${d.username}` : d.kind === "channel" ? "канал" : "группа"}
                      {d.is_creator ? " · владелец" : ""}
                    </span>
                  </span>
                  {d.members != null && (
                    <span className="inline-flex shrink-0 items-center gap-1 text-[11px] text-text-tertiary nums">
                      <Users className="h-3 w-3" strokeWidth={1.8} aria-hidden />
                      {d.members.toLocaleString("ru-RU")}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}

        {items.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2 border-t border-hairline pt-3">
            <button
              type="button"
              disabled={selected.size === 0 || busy}
              onClick={() => leave.mutate({ dialog_ids: [...selected] })}
              className="inline-flex items-center gap-1.5 rounded-pill bg-surface-2 px-3.5 py-2 text-[13px] font-semibold text-text-primary active:opacity-80 disabled:opacity-40"
            >
              <LogOut className="h-4 w-4" strokeWidth={2} aria-hidden />
              Выйти из выбранных{selected.size > 0 ? ` (${selected.size})` : ""}
            </button>
            {confirmClear ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => leave.mutate({ all: true })}
                className="inline-flex items-center gap-1.5 rounded-pill bg-status-critical px-3.5 py-2 text-[13px] font-semibold text-white active:opacity-80 disabled:opacity-40"
              >
                Точно выйти из всех?
              </button>
            ) : (
              <button
                type="button"
                disabled={busy}
                onClick={() => setConfirmClear(true)}
                className="inline-flex items-center gap-1.5 rounded-pill border border-hairline px-3.5 py-2 text-[13px] font-semibold text-status-critical active:bg-surface-2 disabled:opacity-40"
              >
                Очистить все
              </button>
            )}
          </div>
        )}

        {leave.isSuccess && (
          <p className="mt-2 text-[12px] text-text-tertiary">
            Запрос отправлен — список обновится через несколько секунд.
          </p>
        )}
        {(sync.isError || leave.isError) && (
          <p className="mt-2 text-[12px] text-status-critical">
            Не удалось. Проверьте, что воркер запущен, и повторите.
          </p>
        )}
      </div>
    </Section>
  );
}
