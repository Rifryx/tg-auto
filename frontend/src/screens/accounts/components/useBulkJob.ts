import { useCallback, useRef, useState } from "react";
import { bulkApi } from "../../../shared/accounts";
import type { BulkJobDetail } from "../../../shared/types";
import { haptic } from "../../../shared/tg";

type Phase = "idle" | "running" | "done" | "failed";

export interface BulkJobState {
  phase: Phase;
  detail: BulkJobDetail | null;
  /** Результат первого (для карточки аккаунта — единственного) элемента. */
  firstResult: Record<string, unknown> | null;
  /** Ошибка элемента или общая. */
  error: string | null;
  /** Задание выполняется подозрительно долго (воркер не запущен / завис). */
  slow: boolean;
}

const TERMINAL = new Set(["done", "failed", "cancelled"]);

// Через сколько секунд непрерывного «running» показать подсказку о заминке.
const SLOW_AFTER_MS = 20_000;

/* Запускает bulk-action над одним (или несколькими) аккаунтами и опрашивает
   статус задания до завершения. Рассчитан на одиночные действия из карточки
   аккаунта: показывает phase + результат первого item'а.

   onDone вызывается при успешном завершении (напр. инвалидация queries). */
export function useBulkJob(onDone?: (detail: BulkJobDetail) => void) {
  const [state, setState] = useState<BulkJobState>({
    phase: "idle",
    detail: null,
    firstResult: null,
    error: null,
    slow: false,
  });
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startedAt = useRef<number>(0);

  const stop = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  }, []);

  const poll = useCallback(
    (jobId: number) => {
      bulkApi
        .get(jobId)
        .then((detail) => {
          const jobStatus = detail.job.status;
          if (!TERMINAL.has(jobStatus)) {
            timer.current = setTimeout(() => poll(jobId), 1500);
            const slow = Date.now() - startedAt.current > SLOW_AFTER_MS;
            setState((s) => ({ ...s, phase: "running", detail, slow }));
            return;
          }
          // Завершено: читаем первый item.
          const item = detail.items[0] ?? null;
          const failed = jobStatus === "failed" || item?.status === "failed";
          setState({
            phase: failed ? "failed" : "done",
            detail,
            firstResult: item?.result ?? null,
            error: item?.error ?? (failed ? "Задание завершилось с ошибкой" : null),
            slow: false,
          });
          haptic(failed ? "rigid" : "light");
          onDone?.(detail);
        })
        .catch((e: unknown) => {
          setState((s) => ({
            ...s,
            phase: "failed",
            slow: false,
            error: e instanceof Error ? e.message : "Ошибка опроса задания",
          }));
        });
    },
    [onDone],
  );

  const run = useCallback(
    async (actionType: string, accountIds: number[], payload: Record<string, unknown> = {}) => {
      stop();
      startedAt.current = Date.now();
      setState({ phase: "running", detail: null, firstResult: null, error: null, slow: false });
      try {
        const job = await bulkApi.create(actionType, accountIds, payload);
        poll(job.id);
      } catch (e: unknown) {
        setState({
          phase: "failed",
          detail: null,
          firstResult: null,
          error: e instanceof Error ? e.message : "Не удалось создать задание",
          slow: false,
        });
      }
    },
    [poll, stop],
  );

  /* Отслеживать уже созданное задание (напр. из POST /accounts/bulk/set-2fa,
     который создаёт job сам и возвращает его id). */
  const track = useCallback(
    (jobId: number) => {
      stop();
      startedAt.current = Date.now();
      setState({ phase: "running", detail: null, firstResult: null, error: null, slow: false });
      poll(jobId);
    },
    [poll, stop],
  );

  const reset = useCallback(() => {
    stop();
    setState({ phase: "idle", detail: null, firstResult: null, error: null, slow: false });
  }, [stop]);

  return { state, run, track, reset };
}
