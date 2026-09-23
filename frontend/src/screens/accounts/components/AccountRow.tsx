import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import { maskPhone } from "../../../shared/format";
import { PROFILE_LABEL } from "../../../shared/status";
import type { Account } from "../../../shared/types";
import { StatusBadge, StatusDot } from "./ui";

/* Строка аккаунта в списке — мини-карточка (§4/§9 брифа):
   status-dot + маскированный номер + персона слева; бейдж стадии + пресет
   прогрева справа. Тач-таргет ≥ 44px. */
export function AccountRow({ account, groupName }: { account: Account; groupName?: string }) {
  const subtitle = account.username ? `@${account.username}` : "Без персоны";
  return (
    <Link
      to={`/accounts/${account.id}`}
      className="card flex min-h-[64px] items-center gap-3 px-4 py-3 active:bg-surface-2"
    >
      <StatusDot status={account.status} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[15px] font-semibold text-text-primary nums">
          {maskPhone(account.phone)}
        </p>
        <p className="truncate text-[13px] text-text-secondary">
          {subtitle}
          {groupName && <span className="text-text-tertiary"> · {groupName}</span>}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <div className="flex flex-col items-end gap-1">
          <StatusBadge status={account.status} />
          <span className="text-[11px] text-text-tertiary">
            {PROFILE_LABEL[account.warming_profile]}
          </span>
        </div>
        <ChevronRight className="h-4 w-4 text-text-tertiary" strokeWidth={1.8} aria-hidden />
      </div>
    </Link>
  );
}
