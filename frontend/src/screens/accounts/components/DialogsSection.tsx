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
        {/* Skeleton при живом fetch: раньше при клике «Обновить» пользователь
            видел пустую область до нескольких секунд (воркер асинхронно
            снимает getDialogs и 3 раза инвалидирует). Теперь — плейсхолдеры
            строк с pulse-анимацией, чтобы было видно, что процесс идёт. */}
        {sync.isPending && items.length === 0 && <DialogsSkeleton />}
        {!synced && !dialogs.isLoading && !sync.isPending && (
          <p className="py-2 text-center text-[13px] text-text-tertiary">
            Нажмите «Обновить», чтобы загрузить список чатов и каналов аккаунта.
          </p>
        )}
        {synced && items.length === 0 && !sync.isPending && (
          <p className="py-2 text-center text-[13px] text-text-tertiary">
            Аккаунт не состоит ни в одном канале/группе.
          </p>
        )}

        {items.length > 0 && (
          <div className="mb-2 flex items-center justify-between gap-2 border-b border-hairline pb-2">
            <span className="text-[12px] text-text-tertiary nums">
              Выбрано {selected.size} из {items.length}
            </span>
            <button
              type="button"
              onClick={() =>
                setSelected(
                  selected.size === items.length
                    ? new Set()
                    : new Set(items.map((d) => d.id)),
                )
              }
              className="rounded-pill border border-hairline bg-surface-1 px-3 py-1 text-[12px] font-semibold text-text-secondary active:bg-surface-2"
            >
              {selected.size === items.length ? "Снять все" : "Выбрать все"}
            </button>
          </div>
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

/* Плейсхолдер списка чатов/каналов пока sync.isPending. Шесть строк —
   достаточно, чтобы заполнить видимую область до реальных данных и дать
   ощущение прогресса, вместо пустой карточки. Структура повторяет
   реальный item: кружок-аватар, две строки текста, цифра справа. */
function DialogsSkeleton() {
  return (
    <div className="flex flex-col gap-2" aria-busy="true" aria-label="Загружаем список чатов и каналов">
      {Array.from({ length: 6 }).map((_, i) => (
        <div
          key={i}
          className="flex animate-pulse items-center gap-3 rounded-chip px-2 py-2"
          style={{ animationDelay: `${i * 80}ms` }}
        >
          <span className="h-5 w-5 shrink-0 rounded-md bg-surface-2" />
          <span className="h-8 w-8 shrink-0 rounded-full bg-surface-2" />
          <span className="min-w-0 flex-1">
            <span className="block h-3 w-2/3 rounded bg-surface-2" />
            <span className="mt-1.5 block h-2.5 w-1/3 rounded bg-surface-2" />
          </span>
          <span className="h-3 w-10 shrink-0 rounded bg-surface-2" />
        </div>
      ))}
    </div>
  );
}
