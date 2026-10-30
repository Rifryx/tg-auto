import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Clock, ShieldAlert } from "lucide-react";
import { accountsApi } from "../../../shared/accounts";
import { timeAgo } from "../../../shared/format";

/* Результат последней проверки аккаунта (bulk «Проверить» / «Спамблок»).
 *
 * Жалоба: «нигде не показывается результат проверок — написано запущена, а где
 * смотреть непонятно». Проверка обновляет health-снапшот, поэтому показываем его
 * вердикт сразу под шапкой аккаунта: когда проверяли и что нашли (сессия,
 * спамблок, скор). Пока проверка не прошла ни разу — так и пишем. */
export function LastCheckCard({ accountId }: { accountId: number }) {
  const health = useQuery({
    queryKey: ["account", accountId, "health"],
    queryFn: () => accountsApi.health(accountId),
    // Проверка ставится в очередь и отрабатывает за несколько секунд — короткий
    // поллинг, чтобы вердикт появился сам, без ручного обновления.
    refetchInterval: 10_000,
  });
  const h = health.data;
  if (!h) return null;

  const checkedAt = h.last_full_check_at || h.last_session_check_at;
  if (!checkedAt) {
    return (
      <div className="mb-3 flex items-center gap-2 rounded-chip border border-hairline bg-surface-1 px-3 py-2 text-[12px] text-text-tertiary">
        <Clock className="h-4 w-4 shrink-0" strokeWidth={1.8} aria-hidden />
        <span>Проверка ещё не запускалась. Запустите «Проверить» в списке аккаунтов.</span>
      </div>
    );
  }

  const dead = h.session_alive === false;
  const spam = h.spam_blocked === true;
  const ok = !dead && !spam;
  const tone = dead
    ? "border-status-critical/40 bg-status-critical/10 text-status-critical"
    : spam
      ? "border-status-warning/40 bg-status-warning/10 text-status-warning"
      : "border-status-active/40 bg-status-active/10 text-status-active";
  const Icon = dead ? AlertTriangle : spam ? ShieldAlert : CheckCircle2;
  const verdict = dead
    ? "сессия мертва"
    : spam
      ? h.spam_until
        ? `спамблок до ${new Date(h.spam_until).toLocaleString("ru-RU")}`
        : "спамблок"
      : "ОК";

  return (
    <div className={`mb-3 flex items-start gap-2 rounded-chip border px-3 py-2 text-[12px] ${tone}`}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={1.9} aria-hidden />
      <div className="min-w-0 flex-1">
        <span className="font-semibold">Проверка: {verdict}</span>
        <span className="opacity-80">
          {" "}· скор {h.health_score} · {timeAgo(checkedAt)}
        </span>
        {ok && h.spam_blocked === null && (
          <span className="opacity-70"> · спам не проверялся</span>
        )}
      </div>
    </div>
  );
}
