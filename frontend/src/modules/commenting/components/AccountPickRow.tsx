import { Check } from "lucide-react";
import { AccountAvatar } from "../../../shared/AccountAvatar";
import { accountDisplay } from "../../../shared/format";
import { statusDotClass, STATUS_LABEL, accountStatusHint } from "../../../shared/status";
import type { Account } from "../../../shared/types";

/* Карточка-строка аккаунта с чекбоксом (те же строки, что в списке аккаунтов).
 * Под именем показываем статус + ETA («Прогрев · не позже чем через 3 дня»),
 * чтобы пользователь понимал, когда аккаунт освободится — раньше была только
 * пометка «ещё на прогреве» без таймера. */
export function AccountPickRow({
  account,
  selected,
  onToggle,
  note,
}: {
  account: Account;
  selected: boolean;
  onToggle: () => void;
  note?: string;
}) {
  const hint = accountStatusHint(account);
  return (
    <button
      onClick={onToggle}
      className={`card flex min-h-[56px] w-full items-center gap-3 px-4 py-3 text-left active:bg-surface-2 ${selected ? "border-strong" : ""}`}
    >
      <AccountAvatar avatarUrl={account.avatar_url} fallback={account.first_name ?? account.username} size={32} />
      <span className={`h-2 w-2 shrink-0 rounded-full ${statusDotClass(account.status)}`} aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[15px] font-semibold text-text-primary">
          {accountDisplay(account)}
        </p>
        <p className="truncate text-[12px] text-text-tertiary">
          <span className={hint.warn ? "text-status-warning" : undefined}>
            {STATUS_LABEL[account.status]}
          </span>
          {hint.detail && (
            <span className={hint.warn ? "text-status-warning" : undefined}>
              {" · "}
              {hint.detail}
            </span>
          )}
          {note && <span className="text-status-warning"> · {note}</span>}
        </p>
      </div>
      <span
        className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border ${
          selected ? "border-transparent bg-accent text-accent-on" : "border-strong text-transparent"
        }`}
      >
        <Check className="h-3.5 w-3.5" strokeWidth={2.5} aria-hidden />
      </span>
    </button>
  );
}
