import { useMutation } from "@tanstack/react-query";
import { Check, Loader2, Radar, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { subscribeStream } from "../../../shared/api";
import { showToast } from "../../../shared/toast";
import { shillingApi } from "../api";
import type { DiscoveredChannel } from "../types";

type Phase = "form" | "running" | "done";

/**
 * Поиск целей «по пересечению каналов»: сканирует подписки аккаунтов кампании,
 * находит каналы с открытыми комментариями, общие для нескольких аккаунтов, и
 * даёт выбрать, какие добавить в цели. Прогресс — по SSE.
 */
export function IntersectionSheet({
  open,
  campaignId,
  onClose,
  onAdded,
}: {
  open: boolean;
  campaignId: number;
  onClose: () => void;
  onAdded: () => void;
}) {
  const [minAccounts, setMinAccounts] = useState(2);
  const [phase, setPhase] = useState<Phase>("form");
  const [channels, setChannels] = useState<DiscoveredChannel[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [scanned, setScanned] = useState(0);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const unsubRef = useRef<(() => void) | null>(null);
  const watchdogRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Вотчдог: если от воркера нет событий дольше таймаута — не висим вечно.
  const WATCHDOG_MS = 45_000;
  const clearWatchdog = () => {
    if (watchdogRef.current) {
      clearTimeout(watchdogRef.current);
      watchdogRef.current = null;
    }
  };
  const armWatchdog = () => {
    clearWatchdog();
    watchdogRef.current = setTimeout(() => {
      unsubRef.current?.();
      setError(
        "Поиск не отвечает. Проверьте, что запущен воркер (worker), и попробуйте снова.",
      );
      setPhase("done");
    }, WATCHDOG_MS);
  };

  useEffect(
    () => () => {
      unsubRef.current?.();
      clearWatchdog();
    },
    [],
  );

  const scan = useMutation({
    mutationFn: () => shillingApi.discoverIntersection(campaignId, minAccounts),
    onSuccess: ({ job_id }) => {
      setChannels([]);
      setSelected(new Set());
      setScanned(0);
      setTotal(0);
      setError(null);
      setPhase("running");
      armWatchdog();
      const path = shillingApi.intersectionStreamPath(campaignId, job_id);
      unsubRef.current = subscribeStream(path, (raw) => {
        armWatchdog(); // любое событие продлевает ожидание
        const ev = raw as Record<string, unknown>;
        if (ev.event === "start") {
          setTotal(Number(ev.accounts_total) || 0);
        } else if (ev.event === "account_done") {
          setScanned(Number(ev.scanned) || 0);
          setTotal(Number(ev.total) || 0);
        } else if (ev.event === "channel") {
          const ch = ev as unknown as DiscoveredChannel;
          setChannels((prev) =>
            prev.some((c) => c.chat_id === ch.chat_id) ? prev : [...prev, ch],
          );
        } else if (ev.event === "done") {
          clearWatchdog();
          const list = (ev.channels as DiscoveredChannel[] | undefined) ?? [];
          setChannels(list);
          // По умолчанию отмечаем всё, что ещё не в целях.
          setSelected(new Set(list.filter((c) => !c.already_target).map((c) => c.raw_input)));
          if (ev.ok === false) setError(String(ev.reason || "Не удалось выполнить поиск"));
          setPhase("done");
          unsubRef.current?.();
        }
      });
    },
    // Серверная валидация (нет/мало аккаунтов) приходит понятным сообщением.
    onError: (err) => setError((err as Error)?.message || "Не удалось запустить поиск"),
    meta: { silent: true },
  });

  const add = useMutation({
    mutationFn: (raws: string[]) => shillingApi.addTargets(campaignId, raws),
    onSuccess: (created) => {
      showToast(`Добавлено каналов: ${created.length}`, "success");
      onAdded();
      close();
    },
    onError: () => setError("Не удалось добавить каналы"),
    meta: { silent: true },
  });

  if (!open) return null;

  const reset = () => {
    unsubRef.current?.();
    clearWatchdog();
    setPhase("form");
    setChannels([]);
    setSelected(new Set());
    setScanned(0);
    setTotal(0);
    setError(null);
  };
  const close = () => {
    reset();
    onClose();
  };

  const toggle = (raw: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(raw) ? next.delete(raw) : next.add(raw);
      return next;
    });

  const selectable = channels.filter((c) => !c.already_target);
  const allSelected = selectable.length > 0 && selectable.every((c) => selected.has(c.raw_input));
  const toggleAll = () =>
    setSelected(allSelected ? new Set() : new Set(selectable.map((c) => c.raw_input)));

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 sm:items-center">
      <div className="max-h-[90vh] w-full overflow-y-auto rounded-t-card bg-bg-elevated p-5 sm:max-w-lg sm:rounded-card">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-[18px] font-bold text-text-primary">По пересечению каналов</h2>
          <button onClick={close} aria-label="Закрыть" className="text-text-tertiary active:text-text-primary">
            <X className="h-5 w-5" strokeWidth={1.8} aria-hidden />
          </button>
        </div>

        {phase === "form" && (
          <div className="flex flex-col gap-4">
            <p className="text-[13px] leading-snug text-text-tertiary">
              Просканируем подписки аккаунтов кампании и найдём каналы с открытыми
              комментариями, на которые подписаны сразу несколько аккаунтов. Диалоги под
              постами таких каналов выглядят максимально естественно.
            </p>
            <label className="block">
              <span className="mb-1.5 block px-1 text-[13px] text-text-tertiary">
                Минимум общих аккаунтов
              </span>
              <input
                type="number"
                min={1}
                value={minAccounts}
                onChange={(e) => setMinAccounts(Math.max(1, Number(e.target.value) || 1))}
                className="h-11 w-full rounded-chip border border-hairline bg-surface-1 px-4 text-[15px] text-text-primary outline-none focus:border-strong nums"
              />
              <span className="mt-1 block px-1 text-[12px] text-text-tertiary">
                Канал попадёт в список, если на него подписаны минимум столько аккаунтов.
                Нужно ≥2 аккаунта в кампании.
              </span>
            </label>
            {error && <p className="text-[13px] text-status-critical">{error}</p>}
            <button
              onClick={() => scan.mutate()}
              disabled={scan.isPending}
              className="inline-flex h-11 items-center justify-center gap-2 rounded-pill bg-accent text-[15px] font-semibold text-accent-on active:opacity-80 disabled:opacity-40"
            >
              <Radar className="h-4 w-4" strokeWidth={2.2} aria-hidden />
              {scan.isPending ? "Запуск…" : "Сканировать"}
            </button>
          </div>
        )}

        {(phase === "running" || phase === "done") && (
          <div className="flex flex-col gap-3">
            {/* Прогресс */}
            <div className="flex items-center gap-2 text-[13px] text-text-secondary">
              {phase === "running" && (
                <Loader2 className="h-4 w-4 animate-spin text-text-tertiary" strokeWidth={2} aria-hidden />
              )}
              <span>
                Просканировано аккаунтов: <span className="nums text-text-primary">{scanned}/{total || "…"}</span>
              </span>
            </div>

            {/* Список найденных каналов */}
            <div className="flex max-h-[45vh] flex-col gap-1.5 overflow-y-auto rounded-card bg-bg-base p-3">
              {channels.length === 0 ? (
                <p className="py-4 text-center text-[13px] text-text-tertiary">
                  {phase === "running" ? "Ищем пересечения…" : "Общих каналов не найдено."}
                </p>
              ) : (
                channels.map((c) => (
                  <button
                    key={c.chat_id}
                    type="button"
                    onClick={() => !c.already_target && toggle(c.raw_input)}
                    disabled={c.already_target}
                    className="flex items-center gap-2.5 rounded-chip px-2 py-2 text-left active:bg-surface-2 disabled:opacity-50"
                  >
                    <span
                      className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md border ${
                        c.already_target || selected.has(c.raw_input)
                          ? "border-accent bg-accent text-accent-on"
                          : "border-hairline"
                      }`}
                      aria-hidden
                    >
                      {(c.already_target || selected.has(c.raw_input)) && (
                        <Check className="h-3.5 w-3.5" strokeWidth={2.5} />
                      )}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[14px] text-text-primary">
                        {c.title || (c.username ? `@${c.username}` : c.raw_input)}
                      </p>
                      {c.username && c.title && (
                        <p className="truncate text-[12px] text-text-tertiary">@{c.username}</p>
                      )}
                    </div>
                    <span className="shrink-0 rounded-pill bg-surface-1 px-2 py-0.5 text-[11px] text-text-tertiary nums">
                      {c.already_target ? "уже в целях" : `подписано ${c.subscriber_count}/${total}`}
                    </span>
                  </button>
                ))
              )}
            </div>

            {error && <p className="text-[13px] text-status-critical">{error}</p>}

            {phase === "done" && selectable.length > 0 && (
              <button
                onClick={toggleAll}
                className="self-start px-1 text-[13px] text-accent active:opacity-70"
              >
                {allSelected ? "Снять все" : "Выбрать все"}
              </button>
            )}

            <div className="flex gap-2">
              <button
                onClick={reset}
                className="h-11 flex-1 rounded-pill bg-surface-2 text-[14px] font-medium text-text-primary active:opacity-80"
              >
                Заново
              </button>
              {phase === "done" && (
                <button
                  onClick={() => add.mutate([...selected])}
                  disabled={selected.size === 0 || add.isPending}
                  className="inline-flex h-11 flex-1 items-center justify-center gap-1.5 rounded-pill bg-accent text-[14px] font-semibold text-accent-on active:opacity-80 disabled:opacity-40"
                >
                  <Check className="h-4 w-4" strokeWidth={2.4} aria-hidden />
                  {add.isPending ? "Добавляем…" : `Добавить (${selected.size})`}
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
