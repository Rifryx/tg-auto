import { Check } from "lucide-react";
import { maskPhone } from "../../../shared/format";
import { statusDotClass, STATUS_LABEL } from "../../../shared/status";
import type { Account } from "../../../shared/types";

/* Карточка-строка аккаунта с чекбоксом (те же строки, что в списке аккаунтов). */
export function AccountPickRow({
  account,
  selected,
  onToggle,
}: {
  account: Account;
  selected: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      onClick={onToggle}
      className={`card flex min-h-[56px] w-full items-center gap-3 px-4 py-3 text-left active:bg-surface-2 ${selected ? "border-strong" : ""}`}
    >
      <span className={`h-2 w-2 shrink-0 rounded-full ${statusDotClass(account.status)}`} aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[15px] font-semibold text-text-primary nums">
          {maskPhone(account.phone)}
        </p>
        <p className="text-[12px] text-text-tertiary">{STATUS_LABEL[account.status]}</p>
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
