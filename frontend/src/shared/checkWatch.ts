import { accountsApi } from "./accounts";
import { showToast } from "./toast";

/* Глобальный «сторож» проверок аккаунтов.
 *
 * Запрос: «после любой проверки было бы круто, если бы сразу появлялось пуш-
 * уведомление на любом экране». Проверка ставится в очередь и отрабатывает в
 * воркере за несколько секунд, обновляя health-снапшот. Здесь мы, независимо от
 * текущего экрана, поллим health отслеживаемых аккаунтов и, когда у аккаунта
 * обновился last_full_check_at (относительно базового значения на момент
 * запуска), показываем всплывающий тост с вердиктом.
 *
 * Сравниваем именно со СТАРЫМ значением (baseline), а не со временем клиента —
 * иначе рассинхрон часов фронта и бэка давал бы ложные срабатывания. */

interface Pending {
  baseline: string | null;
  since: number;
}

const pending = new Map<number, Pending>();
let timer: ReturnType<typeof setInterval> | null = null;

const POLL_MS = 3000;
const TIMEOUT_MS = 120_000;

export async function watchChecks(accountIds: number[]): Promise<void> {
  await Promise.all(
    accountIds.map(async (id) => {
      let baseline: string | null = null;
      try {
        baseline = (await accountsApi.health(id)).last_full_check_at;
      } catch {
        baseline = null;
      }
      pending.set(id, { baseline, since: Date.now() });
    }),
  );
  ensureLoop();
}

function ensureLoop(): void {
  if (timer != null || pending.size === 0) return;
  timer = setInterval(poll, POLL_MS);
}

function stopLoop(): void {
  if (timer != null) {
    clearInterval(timer);
    timer = null;
  }
}

async function poll(): Promise<void> {
  if (pending.size === 0) {
    stopLoop();
    return;
  }
  const entries = [...pending.entries()];
  await Promise.all(
    entries.map(async ([id, p]) => {
      try {
        const h = await accountsApi.health(id);
        const changed =
          h.last_full_check_at != null && h.last_full_check_at !== p.baseline;
        if (changed) {
          pending.delete(id);
          const bad = h.session_alive === false || h.spam_blocked === true;
          const verdict =
            h.session_alive === false
              ? "сессия мертва"
              : h.spam_blocked === true
                ? "спамблок"
                : "OK";
          showToast(
            `Аккаунт #${id} проверен: ${verdict}`,
            bad ? "error" : "success",
          );
        } else if (Date.now() - p.since > TIMEOUT_MS) {
          pending.delete(id); // не ждём вечно
        }
      } catch {
        /* сеть моргнула — попробуем на следующем тике */
      }
    }),
  );
  if (pending.size === 0) stopLoop();
}
